from observer.accessibility import _read


class Control:
    def __init__(self, name="label", kind="TextControl", *, password=False, children=None):
        self._name = name
        self.ControlTypeName = kind
        self.IsPassword = password
        self.IsOffscreen = False
        self.children = children or []
        self.sibling = None
        for first, second in zip(self.children, self.children[1:]):
            first.sibling = second

    @property
    def Name(self):
        if self.IsPassword or self.ControlTypeName == "EditControl":
            raise AssertionError("Protected control names must never be requested")
        return self._name

    def GetFirstChildControl(self):
        return self.children[0] if self.children else None

    def GetNextSiblingControl(self):
        return self.sibling


class Automation:
    def __init__(self, root, focus=None):
        self.root = root
        self.focus = focus

    def ControlFromHandle(self, handle):
        return self.root

    def GetFocusedControl(self):
        return self.focus


def test_edit_names_and_descendants_are_not_read():
    edit = Control("private input", "EditControl", children=[Control("hidden editable contents")])
    root = Control("Example app", "WindowControl", children=[Control("Build failed"), edit])
    result = _read(Automation(root), 1)
    assert result["labels"] == ["Example app", "Build failed"]


def test_password_control_discards_entire_label_sample():
    root = Control("Example app", "WindowControl", children=[Control("visible"), Control(password=True)])
    result = _read(Automation(root), 1)
    assert result["sensitive"]
    assert not result.get("labels")


def test_focused_password_short_circuits_traversal():
    result = _read(Automation(None, focus=Control(password=True)), 1)
    assert result == {"sensitive": True, "status": "password_field"}


def test_label_collection_is_bounded_and_marked_incomplete():
    root = Control("root", "WindowControl", children=[Control(f"label {i}") for i in range(150)])
    result = _read(Automation(root), 1)
    assert len(result["labels"]) <= 40
    assert result["truncated"]

