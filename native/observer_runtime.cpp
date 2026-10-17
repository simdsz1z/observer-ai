// Persistent local inference against the pinned b11669 DLLs. JSON lines over pipes.
#include "llama.h"
#include "mtmd.h"
#include "mtmd-helper.h"
#include "json.hpp"
#include <chrono>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
using nlohmann::json;

static void quiet(ggml_log_level, const char *, void *) {}
static const char * grammar = R"GRAM(
root ::= "{" "\"a\":" nullable ",\"d\":" nullable ",\"e\":" strings ",\"c\":" strings ",\"t\":" event ",\"i\":" score ",\"q\":" score ",\"r\":" boolean ",\"u\":" nullable "}"
ws ::= ""
nullable ::= string | "null"
string ::= "\"" char* "\""
char ::= [^"\\\x00-\x1f] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F]{4})
strings ::= "[" ws (string (ws "," ws string){0,5})? ws "]"
event ::= "\"observation\"" | "\"activity_change\"" | "\"potential_error\"" | "\"potential_blocker\"" | "\"unknown\""
score ::= "null" | "0.0" | "0.1" | "0.2" | "0.3" | "0.4" | "0.5" | "0.6" | "0.7" | "0.8" | "0.9" | "1.0"
boolean ::= "true" | "false"
)GRAM";

int main(int argc, char ** argv) {
    if (argc != 7) return 2;
    llama_model * model = nullptr;
    llama_context * context = nullptr;
    mtmd_context * vision = nullptr;
    try {
        const auto runtime = std::filesystem::absolute(argv[0]).parent_path().string();
        ggml_backend_load_all_from_path(runtime.c_str());
        llama_backend_init();
        llama_log_set(quiet, nullptr);
        mtmd_helper_log_set(quiet, nullptr);
        auto mp = llama_model_default_params();
        mp.n_gpu_layers = std::stoi(argv[3]);
        ggml_backend_dev_t selected = nullptr;
        for (size_t i = 0; i < ggml_backend_dev_count(); ++i) {
            auto device = ggml_backend_dev_get(i);
            if (std::string(ggml_backend_dev_description(device)).find("NVIDIA") != std::string::npos) {
                selected = device; break;
            }
        }
        ggml_backend_dev_t devices[] = {selected, nullptr};
        if (selected && mp.n_gpu_layers > 0) mp.devices = devices;
        model = llama_model_load_from_file(argv[1], mp);
        if (!model) throw std::runtime_error("model_load_failed");
        auto cp = llama_context_default_params();
        cp.n_ctx = 8192; cp.n_batch = 512; cp.n_ubatch = 512;
        cp.n_threads = cp.n_threads_batch = std::stoi(argv[5]);
        cp.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_ENABLED;
        context = llama_init_from_model(model, cp);
        if (!context) throw std::runtime_error("context_load_failed");
        auto vp = mtmd_context_params_default();
        vp.use_gpu = std::stoi(argv[4]) != 0;
        if (selected && vp.use_gpu) vp.device = selected;
        vp.n_threads = std::stoi(argv[5]);
        vp.image_max_tokens = 256; vp.warmup = false; vp.print_timings = false;
        vp.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_ENABLED;
        vision = mtmd_init_from_file(argv[2], model, vp);
        if (!vision) throw std::runtime_error("vision_load_failed");
        const auto vocab = llama_model_get_vocab(model);
        std::cout << json({{"ready", true}, {"protocol", 1},
                          {"device", selected && mp.n_gpu_layers > 0 ? ggml_backend_dev_description(selected) : "CPU/default"}}).dump() << std::endl;
        std::string line;
        while (std::getline(std::cin, line)) {
            mtmd_helper_bitmap_wrapper media = {};
            mtmd_input_chunks * chunks = nullptr;
            llama_sampler * sampler = nullptr;
            try {
                auto req = json::parse(line);
                if (req.value("quit", false)) break;
                const auto start = std::chrono::steady_clock::now();
                llama_memory_clear(llama_get_memory(context), true);
                auto opt = mtmd_helper_init_opt_default();
                const auto ffmpeg = req.value("ffmpeg_dir", "");
                opt.video_params.ffmpeg_bin_dir = ffmpeg.empty() ? nullptr : ffmpeg.c_str();
                opt.video_params.fps_target = req.value("fps", 1.0f);
                opt.video_params.timestamp_interval_ms = 1000;
                const auto file = req.at("media").get<std::string>();
                media = mtmd_helper_bitmap_init_from_file(vision, file.c_str(), false, opt);
                if (!media.bitmap) throw std::runtime_error("media_load_failed");
                int media_frames = media.video_ctx ? mtmd_helper_video_get_info(media.video_ctx).n_frames : 1;
                const auto system = req.at("system").get<std::string>() +
                    "\nFor this transport, output compact JSON keys a=activity,d=description,e=visible_errors,c=changes,"
                    "t=event_type,i=importance,q=confidence,r=requires_supervisor_review,u=uncertainty. "
                    "Do not output task_context; the application attaches the stated goal. No formatting whitespace outside strings.";
                const auto prompt = std::string(mtmd_default_marker()) + req.at("prompt").get<std::string>();
                llama_chat_message messages[] = {{"system", system.c_str()}, {"user", prompt.c_str()}};
                const auto tmpl = llama_model_chat_template(model, nullptr);
                std::vector<char> formatted(65536);
                const int size = llama_chat_apply_template(tmpl, messages, 2, true, formatted.data(), formatted.size());
                if (size < 0 || size >= (int)formatted.size()) throw std::runtime_error("prompt_too_large");
                const std::string text(formatted.data(), size);
                mtmd_input_text input = {text.c_str(), text.size(), true, true};
                chunks = mtmd_input_chunks_init();
                const mtmd_bitmap * bitmaps[] = {media.bitmap};
                if (mtmd_tokenize(vision, chunks, &input, bitmaps, 1)) throw std::runtime_error("media_tokenize_failed");
                const auto input_tokens = mtmd_helper_get_n_tokens(chunks);
                if (input_tokens + 384 >= 8192) throw std::runtime_error("context_limit");
                llama_pos pos = 0;
                if (mtmd_helper_eval_chunks(vision, context, chunks, 0, 0, 512, true, &pos)) throw std::runtime_error("media_eval_failed");
                const auto prefilled = std::chrono::steady_clock::now();
                sampler = llama_sampler_init_grammar(vocab, grammar, "root");
                if (!sampler) throw std::runtime_error("grammar_init_failed");
                std::string answer;
                int tokens = 0;
                bool complete = false;
                for (; tokens < 384; ++tokens) {
                    const float * logits = llama_get_logits_ith(context, -1);
                    const int vocabulary = llama_vocab_n_tokens(vocab);
                    llama_token token = 0;
                    for (int j = 1; j < vocabulary; ++j) if (logits[j] > logits[token]) token = j;
                    llama_token_data candidate = {token, logits[token], 0.0f};
                    llama_token_data_array check = {&candidate, 1, -1, false};
                    llama_sampler_apply(sampler, &check);
                    // Most predicted tokens already satisfy the grammar. Avoid checking
                    // the full 151k-token vocabulary unless the best token is rejected.
                    if (!std::isfinite(candidate.logit)) {
                        std::vector<llama_token_data> data(vocabulary);
                        for (int j = 0; j < vocabulary; ++j) data[j] = {j, logits[j], 0.0f};
                        llama_token_data_array all = {data.data(), data.size(), -1, false};
                        llama_sampler_apply(sampler, &all);
                        int best = 0;
                        for (int j = 1; j < vocabulary; ++j) if (data[j].logit > data[best].logit) best = j;
                        if (!std::isfinite(data[best].logit)) throw std::runtime_error("grammar_no_token");
                        token = data[best].id;
                    }
                    llama_sampler_accept(sampler, token);
                    if (llama_vocab_is_eog(vocab, token)) { complete = true; break; }
                    char piece[4096];
                    int len = llama_token_to_piece(vocab, token, piece, sizeof(piece), 0, false);
                    if (len < 0) throw std::runtime_error("token_decode_failed");
                    answer.append(piece, len);
                    auto batch = llama_batch_get_one(&token, 1);
                    if (llama_decode(context, batch)) throw std::runtime_error("generation_failed");
                }
                if (!complete) throw std::runtime_error("output_token_limit");
                auto wire = json::parse(answer);
                json canonical = {{"activity", wire.at("a")}, {"description", wire.at("d")},
                                  {"visible_errors", wire.at("e")}, {"changes", wire.at("c")}, {"task_context", nullptr},
                                  {"event_type", wire.at("t")}, {"importance", wire.at("i")}, {"confidence", wire.at("q")},
                                  {"requires_supervisor_review", wire.at("r")}, {"uncertainty", wire.at("u")}};
                const auto end = std::chrono::steady_clock::now();
                auto ms = [](auto a, auto b) { return std::chrono::duration<double, std::milli>(b-a).count(); };
                std::cout << json({{"ok", true}, {"answer", canonical.dump()}, {"input_tokens", input_tokens},
                                  {"output_tokens", tokens}, {"media_frames", media_frames},
                                  {"prefill_ms", ms(start, prefilled)}, {"generation_ms", ms(prefilled, end)}}).dump() << std::endl;
            } catch (const std::exception & e) {
                std::cout << json({{"ok", false}, {"error", e.what()}}).dump() << std::endl;
            }
            if (sampler) llama_sampler_free(sampler);
            if (chunks) mtmd_input_chunks_free(chunks);
            if (media.bitmap) mtmd_bitmap_free(media.bitmap);
            if (media.video_ctx) mtmd_helper_video_free(media.video_ctx);
        }
    } catch (const std::exception & e) {
        std::cout << json({{"ready", false}, {"error", e.what()}}).dump() << std::endl;
    }
    if (vision) mtmd_free(vision);
    if (context) llama_free(context);
    if (model) llama_model_free(model);
    llama_backend_free();
    return 0;
}
