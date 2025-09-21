import json
import math
from dataclasses import dataclass, field
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, simpledialog, messagebox, ttk
from typing import Any, Dict, Iterable, List, Optional, Tuple, Set

# --------- Configuration ---------
NODE_W = 160
NODE_H = 56
HORIZ_GAP = 60
VERT_GAP = 36
FONT = ("Segoe UI", 11)
SEL_OUTLINE = "#0ea5e9"
EDGE_COLOR = "#555"
BG = "#fbfbfd"
NODE_OUTLINE = "#d4d4d8"
NODE_MARGIN = 18
ZOOM_STEP = 1.1
ZOOM_MIN = 0.4
ZOOM_MAX = 2.5
PAN_STEP = 60
DEFAULT_STATUS = (
    "Use the menu bar or shortcuts (A=Add child, Enter=Edit, Del=Delete). "
    "Double-click canvas to add a node; drag to move."
)

PALETTE_COLORS = [
    "#B9C2FF",
    "#FFB3BE",
    "#FFF49A",
    "#C6FFB0",
    "#B7F0FF",
    "#DDB096",
    "#B5A0DD",
    "#9DDDD0",
    "#DDA0B7",
    "#B1DD53",
]

LEVEL_COLORS = PALETTE_COLORS

@dataclass
class Workspace:
    frame: tk.Frame
    canvas: tk.Canvas
    status_var: tk.StringVar
    name: str = "Workspace"
    nodes: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    parent: Dict[int, Optional[int]] = field(default_factory=dict)
    canvas_items: Dict[int, Dict[str, int]] = field(default_factory=dict)
    edge_offsets: Dict[Tuple[int, int], float] = field(default_factory=dict)
    palette_index: int = 0
    item_to_node: Dict[int, int] = field(default_factory=dict)
    selected_ids: Set[int] = field(default_factory=set)
    primary_selected: Optional[int] = None
    dragging: Dict[str, Any] = field(
        default_factory=lambda: {
            "mode": None,
            "id": None,
            "dx": 0.0,
            "dy": 0.0,
            "start_x": 0.0,
            "start_y": 0.0,
            "offset_x": 0.0,
            "offset_y": 0.0,
        }
    )
    root_id: Optional[int] = None
    next_id: int = 1
    path: Optional[str] = None
    scale: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0


class MindMapApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Mind Map (tk) - drag, add, save, auto-layout")

        self.workspaces: Dict[tk.Widget, Workspace] = {}
        self._current_ws: Optional[Workspace] = None
        self._workspace_counter = 0

        self._build_ui()
        self._font = tkfont.Font(root, font=FONT)
        self._init_color_tools()
        self._create_workspace()
        self._update_title()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New Workspace", command=self.new_workspace)
        file_menu.add_separator()
        file_menu.add_command(label="Save", command=self.save)
        file_menu.add_command(label="Load", command=self.load)
        menubar.add_cascade(label="File", menu=file_menu)

        mind_menu = tk.Menu(menubar, tearoff=False)
        mind_menu.add_command(label="New Root", command=self.new_root)
        mind_menu.add_command(label="Set Root", command=self.set_root)
        mind_menu.add_separator()
        mind_menu.add_command(label="Auto Layout", command=self.auto_layout)
        menubar.add_cascade(label="Mind Map", menu=mind_menu)

        node_menu = tk.Menu(menubar, tearoff=False)
        node_menu.add_command(label="Add Child", command=self.add_child, accelerator="A")
        node_menu.add_command(label="Edit Node", command=self.edit_selected, accelerator="Enter")
        node_menu.add_command(label="Delete Node", command=self.delete_selected, accelerator="Del")
        menubar.add_cascade(label="Node", menu=node_menu)

        self.root.config(menu=menubar)
        self.root.bind("<Key-a>", lambda _: self.add_child())
        self.root.bind("<Delete>", lambda _: self.delete_selected())
        self.root.bind("<BackSpace>", lambda _: self.delete_selected())
        self.root.bind("<Return>", lambda _: self.edit_selected())
        self.root.bind("<Up>", lambda _: self.pan_by(0, PAN_STEP))
        self.root.bind("<Down>", lambda _: self.pan_by(0, -PAN_STEP))
        self.root.bind("<Left>", lambda _: self.pan_by(PAN_STEP, 0))
        self.root.bind("<Right>", lambda _: self.pan_by(-PAN_STEP, 0))
        self.root.bind("<Control-plus>", lambda _: self.zoom(ZOOM_STEP))
        self.root.bind("<Control-KP_Add>", lambda _: self.zoom(ZOOM_STEP))
        self.root.bind("<Control-equal>", lambda _: self.zoom(ZOOM_STEP))
        self.root.bind("<Control-minus>", lambda _: self.zoom(1 / ZOOM_STEP))
        self.root.bind("<Control-KP_Subtract>", lambda _: self.zoom(1 / ZOOM_STEP))
        self.root.bind("<Control-0>", lambda _: self.reset_view())

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._status_placeholder = tk.StringVar(value=DEFAULT_STATUS)
        self.status_label = tk.Label(self.root, textvariable=self._status_placeholder, anchor="w", bg="white")
        self.status_label.pack(fill=tk.X, side=tk.BOTTOM)

        self._build_level_panel()

    def _init_color_tools(self) -> None:
        self._color_palette = PALETTE_COLORS[:] if PALETTE_COLORS else LEVEL_COLORS[:] or ["#fef9c3"]
        self._palette_cols = 5
        self._palette_window: Optional[tk.Toplevel] = None
        self._context_node: Optional[int] = None
        self.level_vars: Dict[int, tk.BooleanVar] = {}
        self._updating_level_checks = False

    def _build_level_panel(self) -> None:
        self.level_panel = tk.Frame(self.root, bg="#ffffff", bd=1, relief="ridge")
        self.level_panel.place(relx=1.0, rely=0.0, anchor="ne", x=-12, y=12)
        header = tk.Label(self.level_panel, text="Levels", bg="#ffffff", font=("Segoe UI", 9, "bold"))
        header.pack(padx=6, pady=(4, 2))
        self.level_body = tk.Frame(self.level_panel, bg="#ffffff")
        self.level_body.pack(padx=6, pady=(0, 6))
        self.level_vars = {}
        self._refresh_level_panel()

    def _refresh_level_panel(self) -> None:
        if not hasattr(self, "level_body"):
            return
        self._updating_level_checks = True
        for child in self.level_body.winfo_children():
            child.destroy()
        self.level_vars = {}
        if not self._current_ws:
            tk.Label(self.level_body, text="No nodes", bg="#ffffff", font=("Segoe UI", 9)).pack()
            self._updating_level_checks = False
            return
        self._updating_level_checks = True
        for child in self.level_body.winfo_children():
            child.destroy()
        self.level_vars = {}
        levels = sorted({self._node_depth(nid) for nid in self.nodes}) if self.nodes else []
        if not levels:
            tk.Label(self.level_body, text="No nodes", bg="#ffffff", font=("Segoe UI", 9)).pack()
            self._updating_level_checks = False
            return
        for level in levels:
            var = tk.BooleanVar(value=False)
            chk = tk.Checkbutton(
                self.level_body,
                text=f"Level {level}",
                variable=var,
                command=lambda lvl=level: self._on_level_toggle(lvl),
                bg="#ffffff",
                anchor="w",
            )
            chk.pack(anchor="w")
            self.level_vars[level] = var
        self._updating_level_checks = False

    def _clear_level_checks(self) -> None:
        if not getattr(self, "level_vars", None):
            return
        self._updating_level_checks = True
        for var in self.level_vars.values():
            var.set(False)
        self._updating_level_checks = False

    def _on_level_toggle(self, level: int) -> None:
        if self._updating_level_checks:
            return
        levels = [lvl for lvl, var in self.level_vars.items() if var.get()]
        if not levels:
            self.selected_ids = set()
            return
        ids = {nid for nid in self.nodes if self._node_depth(nid) in levels}
        self.selected_ids = ids


    def _bind_canvas(self, canvas: tk.Canvas) -> None:
        canvas.bind("<Button-1>", self.on_click)
        canvas.bind("<Double-Button-1>", self.on_double_click)
        canvas.bind("<B1-Motion>", self.on_drag)
        canvas.bind("<ButtonRelease-1>", self.on_release)
        canvas.bind("<Control-MouseWheel>", self._on_ctrl_wheel)
        canvas.bind("<MouseWheel>", self._on_wheel_scroll)

    # ---------- Workspace management ----------
    def _create_workspace(self, name: Optional[str] = None, path: Optional[str] = None) -> Workspace:
        if name is None:
            self._workspace_counter += 1
            name = f"Workspace {self._workspace_counter}"
        else:
            self._workspace_counter += 1

        frame = tk.Frame(self.notebook, bg=BG)
        canvas = tk.Canvas(frame, bg=BG, highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        status_var = tk.StringVar(value=DEFAULT_STATUS)
        workspace = Workspace(frame=frame, canvas=canvas, status_var=status_var, name=name, path=path)
        self.workspaces[frame] = workspace

        self.notebook.add(frame, text=name)
        self._bind_canvas(canvas)
        self.notebook.select(frame)
        self._set_active_workspace(workspace)
        self._refresh_level_panel()
        return workspace

    def _set_active_workspace(self, workspace: Workspace) -> None:
        self._current_ws = workspace
        self.status_label.config(textvariable=workspace.status_var)
        self._update_title()
        self._highlight_selection()

    def _rename_workspace(self, workspace: Workspace, name: str) -> None:
        workspace.name = name
        self.notebook.tab(workspace.frame, text=name)
        if workspace is self._current_ws:
            self._update_title()

    def _on_tab_changed(self, event: tk.Event) -> None:
        tab_id = event.widget.select()
        if not tab_id:
            return
        frame = event.widget.nametowidget(tab_id)
        workspace = self.workspaces.get(frame)
        if workspace:
            self._set_active_workspace(workspace)

    def _set_status(self, message: str) -> None:
        if self._current_ws is not None:
            self._current_ws.status_var.set(message)
        else:
            self._status_placeholder.set(message)

    def new_workspace(self) -> None:
        workspace = self._create_workspace()
        workspace.scale = 1.0
        workspace.offset_x = 0.0
        workspace.offset_y = 0.0
        self._set_status(f"{workspace.name} ready.")

    # ---------- Convenience properties ----------
    @property
    def ws(self) -> Workspace:
        if self._current_ws is None:
            raise RuntimeError("No active workspace")
        return self._current_ws

    @property
    def canvas(self) -> tk.Canvas:
        return self.ws.canvas

    @property
    def nodes(self) -> Dict[int, Dict[str, Any]]:
        return self.ws.nodes

    @property
    def parent(self) -> Dict[int, Optional[int]]:
        return self.ws.parent

    @property
    def canvas_items(self) -> Dict[int, Dict[str, int]]:
        return self.ws.canvas_items

    @property
    def item_to_node(self) -> Dict[int, int]:
        return self.ws.item_to_node

    @property
    def selected_ids(self) -> Set[int]:
        return self.ws.selected_ids

    @selected_ids.setter
    def selected_ids(self, values: Iterable[int]) -> None:
        ids = set(values)
        current_primary = self.ws.primary_selected
        if current_primary in ids:
            primary = current_primary
        else:
            primary = next(iter(ids), None)
        self.ws.selected_ids = ids
        self.ws.primary_selected = primary
        self._highlight_selection()

    @property
    def selected_id(self) -> Optional[int]:
        return self.ws.primary_selected

    @selected_id.setter
    def selected_id(self, value: Optional[int]) -> None:
        if value is None:
            self.selected_ids = set()
        else:
            self.selected_ids = {value}

    @property
    def dragging(self) -> Dict[str, Any]:
        return self.ws.dragging

    @dragging.setter
    def dragging(self, value: Dict[str, Any]) -> None:
        self.ws.dragging = value

    @property
    def root_id(self) -> Optional[int]:
        return self.ws.root_id

    @root_id.setter
    def root_id(self, value: Optional[int]) -> None:
        self.ws.root_id = value

    @property
    def next_id(self) -> int:
        return self.ws.next_id

    @next_id.setter
    def next_id(self, value: int) -> None:
        self.ws.next_id = value

    @property
    def current_path(self) -> Optional[str]:
        return self.ws.path

    @current_path.setter
    def current_path(self, value: Optional[str]) -> None:
        self.ws.path = value

    # ---------- Coordinate helpers ----------
    def _to_canvas_point(self, x: float, y: float) -> Tuple[float, float]:
        ws = self.ws
        return ws.offset_x + x * ws.scale, ws.offset_y + y * ws.scale

    def _from_canvas_point(self, x: float, y: float) -> Tuple[float, float]:
        ws = self.ws
        if ws.scale == 0:
            return x, y
        return (x - ws.offset_x) / ws.scale, (y - ws.offset_y) / ws.scale

    def _node_center(self, nid: int) -> Tuple[float, float]:
        node = self.nodes[nid]
        return self._to_canvas_point(node["x"], node["y"])

    def _node_at(self, x: float, y: float) -> Optional[int]:
        hits = self.canvas.find_overlapping(x, y, x, y)
        for item in reversed(hits):
            nid = self.item_to_node.get(item)
            if nid is not None:
                return nid
        return None

    def _node_bbox(self, nid: int) -> Tuple[float, float, float, float]:
        cx, cy = self._node_center(nid)
        node = self.nodes.get(nid, {})
        base_w = node.get("w", NODE_W)
        base_h = node.get("h", NODE_H)
        scale = self.ws.scale or 1.0
        half_w = (base_w * scale) / 2
        half_h = (base_h * scale) / 2
        return (cx - half_w, cy - half_h, cx + half_w, cy + half_h)

    def _refresh_node_position(self, nid: int) -> None:
        items = self.canvas_items.get(nid)
        if not items:
            return
        x0, y0, x1, y1 = self._node_bbox(nid)
        self.canvas.coords(items["shape"], x0, y0, x1, y1)
        self._render_node_text(nid)

    def _refresh_all_positions(self) -> None:
        for nid in self.nodes:
            self._refresh_node_position(nid)
    # ---------- Node helpers ----------
    def _new_id(self) -> int:
        nid = self.next_id
        self.next_id += 1
        return nid

    def new_root(self) -> None:
        self.canvas.update_idletasks()
        cx = self.canvas.winfo_width() // 2 or 400
        cy = self.canvas.winfo_height() // 2 or 300
        lx, ly = self._from_canvas_point(cx, cy)
        nid = self._create_node("Root", lx, ly, depth=0)
        self._set_root(nid)
        self._select(nid)
        self._set_status("Root created.")

    def add_child(self) -> None:
        if not self.selected_id:
            self._set_status("Select a node first, then press A or use Node > Add Child.")
            return
        parent_id = self.selected_id
        parent_node = self.nodes[parent_id]
        base_x = parent_node["x"] + NODE_W + HORIZ_GAP
        if parent_id == self.root_id and len(self.nodes[parent_id]["children"]) % 2 == 1:
            base_x = parent_node["x"] - NODE_W - HORIZ_GAP
        base_y = parent_node["y"]
        new_x, new_y = self._find_free_position(base_x, base_y)
        depth = self._node_depth(parent_id) + 1
        nid = self._create_node("New Node", new_x, new_y, depth=depth)
        self._add_edge(parent_id, nid)
        self._select(nid)
        self._set_status("Child node added.")

    def delete_selected(self) -> None:
        nid = self.selected_id
        if not nid:
            self._set_status("Nothing selected to delete.")
            return
        count = self._subtree_size(nid)
        if count > 1:
            if not messagebox.askyesno("Delete", f"Delete this node and its {count - 1} descendant(s)?"):
                return
        ids = list(self._collect_subtree(nid))
        for cid in ids:
            for ch in list(self.nodes[cid]["children"]):
                self.parent[ch] = None
            parent_id = self.parent.get(cid)
            if parent_id is not None and cid in self.nodes[parent_id]["children"]:
                self.nodes[parent_id]["children"].remove(cid)
            self._delete_canvas_for_node(cid)
            self.parent.pop(cid, None)
            self.nodes.pop(cid, None)
        if self.root_id in ids:
            self.root_id = next(iter(self.nodes), None)
        self.selected_id = None
        self.redraw()
        self._refresh_level_panel()
        self._set_status("Node deleted.")

    def edit_selected(self) -> None:
        nid = self.selected_id
        if not nid:
            self._set_status("Select a node to edit.")
            return
        current = self.nodes[nid]["text"]

        editor = tk.Toplevel(self.root)
        editor.title("Edit Node")
        editor.transient(self.root)
        editor.grab_set()
        toolbar = tk.Frame(editor)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 4))

        text_widget = tk.Text(editor, wrap="word", font=FONT)
        text_widget.insert("1.0", current)
        text_widget.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        def apply_wrapper(prefix: str, suffix: str) -> None:
            try:
                start = text_widget.index("sel.first")
                end = text_widget.index("sel.last")
            except tk.TclError:
                return
            selection = text_widget.get(start, end)
            text_widget.delete(start, end)
            text_widget.insert(start, f"{prefix}{selection}{suffix}")

        def apply_bullets() -> None:
            try:
                start = text_widget.index("sel.first linestart")
                end = text_widget.index("sel.last lineend")
            except tk.TclError:
                start = "1.0"
                end = "end-1c"
            block = text_widget.get(start, end)
            lines = block.split("\n")
            formatted = ["- " + line.lstrip("- ") if line.strip() else "-" for line in lines]
            text_widget.delete(start, end)
            text_widget.insert(start, "\n".join(formatted))

        def apply_numbering() -> None:
            try:
                start = text_widget.index("sel.first linestart")
                end = text_widget.index("sel.last lineend")
            except tk.TclError:
                start = "1.0"
                end = "end-1c"
            block = text_widget.get(start, end)
            lines = block.split("\n")
            numbered = [f"{i + 1}. {line.lstrip('0123456789. ')}" if line.strip() else f"{i + 1}." for i, line in enumerate(lines)]
            text_widget.delete(start, end)
            text_widget.insert(start, "\n".join(numbered))

        tk.Button(toolbar, text="Bold", command=lambda: apply_wrapper("**", "**")).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="Italic", command=lambda: apply_wrapper("_", "_")).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="Bullet", command=apply_bullets).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="Number", command=apply_numbering).pack(side=tk.LEFT, padx=2)

        def persist_text() -> None:
            new_text = text_widget.get("1.0", "end").rstrip("\n")
            text = new_text if new_text.strip() else " "
            self.nodes[nid]["text"] = text
            self._update_node_label(nid)
            self._set_status("Node text updated.")

        def save_and_close() -> None:
            persist_text()
            editor.destroy()

        def cancel() -> None:
            editor.destroy()

        button_group = tk.Frame(toolbar)
        button_group.pack(side=tk.RIGHT, padx=(0, 4))
        tk.Button(button_group, text="Confirm", command=save_and_close).pack(side=tk.RIGHT, padx=2)
        tk.Button(button_group, text="Save", command=persist_text).pack(side=tk.RIGHT, padx=2)
        tk.Button(button_group, text="Cancel", command=cancel).pack(side=tk.RIGHT, padx=2)

        editor.update_idletasks()
        editor.geometry("420x200")
        editor.minsize(420, 200)
        editor.protocol("WM_DELETE_WINDOW", cancel)
        editor.bind("<Escape>", lambda _e: cancel())
        editor.wait_window()

    def _next_auto_color(self) -> str:
        palette = getattr(self, "_color_palette", []) or LEVEL_COLORS or ["#ffffff"]
        ws = self.ws
        color = palette[ws.palette_index % len(palette)]
        ws.palette_index += 1
        return color


    def set_root(self) -> None:
        nid = self.selected_id
        if not nid:
            self._set_status("Select a node to set it as root.")
            return
        self._set_root(nid)
        self._set_status(f"Root set to node {nid} ({self.nodes[nid]['text']}).")

    def _set_root(self, nid: int) -> None:
        self.root_id = nid
        self.parent[nid] = None
        self._update_title()

    def _create_node(self, text: str, x: float, y: float, depth: Optional[int] = None) -> int:
        nx, ny = self._find_free_position(x, y)
        nid = self._new_id()
        if depth is None:
            depth = 0
        fill = self._next_auto_color()
        self.nodes[nid] = {
            "text": text,
            "x": nx,
            "y": ny,
            "children": [],
            "fill": fill,
            "custom": True,
            "w": NODE_W,
            "h": NODE_H,
        }
        self.parent[nid] = None
        shape, texts = self._draw_node(nid)
        self.canvas_items[nid] = {"shape": shape, "texts": texts}
        self._update_node_size(nid)
        self.redraw_edges_of_node_and_neighbors(nid)
        if self.root_id is None:
            self._set_root(nid)
        self._refresh_level_panel()
        return nid

    def _draw_node(self, nid: int) -> Tuple[int, List[int]]:
        x0, y0, x1, y1 = self._node_bbox(nid)
        fill = self.nodes[nid].get("fill") or self._default_fill_for_depth(self._node_depth(nid))
        self.nodes[nid]["fill"] = fill
        self.nodes[nid].setdefault("custom", False)
        shape = self.canvas.create_oval(
            x0,
            y0,
            x1,
            y1,
            fill=fill,
            outline=NODE_OUTLINE,
            width=2,
            tags=("node", "node-shape"),
        )
        self.item_to_node[shape] = nid
        texts: List[int] = []
        items = self.canvas_items.get(nid)
        if items:
            items["shape"] = shape
            items["texts"] = []
        else:
            self.canvas_items[nid] = {"shape": shape, "texts": []}
        self._render_node_text(nid)
        texts = list(self.canvas_items[nid].get("texts", []))
        for item in [shape] + texts:
            self.item_to_node[item] = nid
            self.canvas.tag_bind(item, "<Button-1>", lambda e, n=nid: self.on_click_node(e, n))
            self.canvas.tag_bind(item, "<Double-Button-1>", lambda e, n=nid: self.on_double_click_node(e, n))
            self.canvas.tag_bind(item, "<Button-3>", lambda e, n=nid: self.on_node_context(e, n))
        return shape, texts

    def _update_node_label(self, nid: int) -> None:
        self._update_node_size(nid)

    def _update_node_fill(self, nid: int) -> None:
        items = self.canvas_items.get(nid)
        if not items:
            return
        fill = self.nodes[nid].get("fill") or self._default_fill_for_depth(self._node_depth(nid))
        self.nodes[nid]["fill"] = fill
        self.canvas.itemconfigure(items["shape"], fill=fill)

    def _delete_canvas_for_node(self, nid: int) -> None:
        items = self.canvas_items.pop(nid, None)
        if not items:
            return
        self.item_to_node.pop(items.get("shape"), None)
        for tid in items.get("texts", []):
            self.item_to_node.pop(tid, None)
            self.canvas.delete(tid)
        if "shape" in items:
            self.canvas.delete(items["shape"])

    def _select(self, nid: Optional[int], additive: bool = False) -> None:
        if not additive:
            self._clear_level_checks()
        ids = set(self.selected_ids)
        if nid is None:
            ids.clear()
        else:
            if additive:
                if nid in ids:
                    ids.remove(nid)
                else:
                    ids.add(nid)
            else:
                ids = {nid}
        self.selected_ids = ids

    def _highlight_selection(self) -> None:
        selected = self.selected_ids
        for nid, items in self.canvas_items.items():
            outline = NODE_OUTLINE
            width = 2
            if nid in selected:
                outline = SEL_OUTLINE
                width = 3
            self.canvas.itemconfigure(items["shape"], outline=outline, width=width)
            for tid in items.get("texts", []):
                self.canvas.tag_raise(tid, items["shape"])
    # ---------- Graph helpers ----------
    def _add_edge(self, parent_id: int, child_id: int) -> None:
        current_parent = self.parent.get(child_id)
        if current_parent is not None and child_id in self.nodes[current_parent]["children"]:
            self.nodes[current_parent]["children"].remove(child_id)
        self.parent[child_id] = parent_id
        if child_id not in self.nodes[parent_id]["children"]:
            self.nodes[parent_id]["children"].append(child_id)
        if child_id == self.root_id:
            self._set_root(parent_id)
        if not self.nodes[child_id].get("custom"):
            depth = self._node_depth(child_id)
            self.nodes[child_id]["fill"] = self._default_fill_for_depth(depth)
            self._update_node_fill(child_id)
        self.redraw_edges_of_node_and_neighbors(child_id)

    def _edges(self) -> Iterable[Tuple[int, int]]:
        for pid, info in self.nodes.items():
            for cid in info["children"]:
                yield pid, cid

    def _edge_exit_point(self, nid: int, target_x: float, target_y: float) -> Tuple[float, float]:
        cx, cy = self._node_center(nid)
        a = max(NODE_W * self.ws.scale / 2, 1.0)
        b = max(NODE_H * self.ws.scale / 2, 1.0)
        dx = target_x - cx
        dy = target_y - cy
        if abs(dx) < 1e-4 and abs(dy) < 1e-4:
            dx, dy = 0.0, b
        factor = math.sqrt((dx * dx) / (a * a) + (dy * dy) / (b * b))
        if factor == 0:
            factor = 1.0
        t = 1.0 / factor
        sx = cx + dx * t
        sy = cy + dy * t
        margin = max(1.5, self.ws.scale * 1.2)
        vx, vy = dx * t, dy * t
        length = math.hypot(vx, vy) or 1.0
        sx += (vx / length) * margin
        sy += (vy / length) * margin
        return sx, sy

    def _update_node_size(self, nid: int) -> None:
        node = self.nodes[nid]
        text = node.get("text", " ") or " "
        parsed = self._parse_formatted_lines(text)
        if not parsed:
            parsed = [[(" ", False, False)]]

        padding_side = 14
        padding_top = 12
        padding_bottom = 12
        line_gap = 4

        base_font = getattr(self, "_font", tkfont.Font(self.root, font=FONT))
        max_width = 0.0
        total_height = 0.0
        for line in parsed:
            if line:
                line_height = max(self._get_font_variant(bold, italic).metrics("linespace") for _, bold, italic in line)
                line_width = sum(self._get_font_variant(bold, italic).measure(segment) for segment, bold, italic in line)
            else:
                line_height = base_font.metrics("linespace")
                line_width = base_font.measure(" ")
            max_width = max(max_width, float(line_width))
            total_height += float(line_height)
        if parsed:
            total_height += line_gap * max(0, len(parsed) - 1)

        width = max_width + padding_side * 2
        height = total_height + padding_top + padding_bottom
        node["w"] = max(width, NODE_W)
        node["h"] = max(height, NODE_H)
        items = self.canvas_items.get(nid)
        if items:
            self._refresh_node_position(nid)

    def _default_fill_for_depth(self, depth: int) -> str:
        if not LEVEL_COLORS:
            return "white"
        return LEVEL_COLORS[depth % len(LEVEL_COLORS)]

    def _node_depth(self, nid: int) -> int:
        depth = 0
        current = nid
        visited = set()
        while True:
            parent_id = self.parent.get(current)
            if parent_id is None or parent_id in visited:
                break
            depth += 1
            visited.add(current)
            current = parent_id
        return depth

    def _symmetrical_positions(self, count: int) -> List[float]:
        if count <= 0:
            return []
        positions: List[float] = []
        if count % 2 == 0:
            offset = 0.5
            while len(positions) < count:
                positions.extend([-offset, offset])
                offset += 1.0
        else:
            positions.append(0.0)
            offset = 1.0
            while len(positions) < count:
                positions.extend([-offset, offset])
                offset += 1.0
        positions = positions[:count]
        positions.sort()
        return positions


    def _get_font_variant(self, bold: bool, italic: bool) -> tkfont.Font:
        key = (bold, italic)
        if not hasattr(self, "_font_variants"):
            base = getattr(self, "_font", tkfont.Font(self.root, font=FONT))
            self._font = base
            self._font_variants = {
                (False, False): base,
                (True, False): tkfont.Font(self.root, font=FONT),
                (False, True): tkfont.Font(self.root, font=FONT),
                (True, True): tkfont.Font(self.root, font=FONT),
            }
            self._font_variants[(True, False)].configure(weight="bold")
            self._font_variants[(False, True)].configure(slant="italic")
            self._font_variants[(True, True)].configure(weight="bold", slant="italic")
        elif key not in self._font_variants:
            base = getattr(self, "_font", tkfont.Font(self.root, font=FONT))
            variant = tkfont.Font(self.root, font=base)
            variant.configure(weight="bold" if bold else "normal", slant="italic" if italic else "roman")
            self._font_variants[key] = variant
        return self._font_variants[key]

    def _parse_formatted_lines(self, text: str) -> List[List[Tuple[str, bool, bool]]]:
        lines = text.split("\n") if text else [""]
        parsed: List[List[Tuple[str, bool, bool]]] = []
        bold = False
        italic = False
        for raw in lines:
            segments: List[Tuple[str, bool, bool]] = []
            buf: List[str] = []
            line_start_bold = bold
            line_start_italic = italic
            i = 0
            while i < len(raw):
                if raw.startswith("**", i):
                    if buf:
                        segments.append((''.join(buf), bold, italic))
                        buf.clear()
                    bold = not bold
                    i += 2
                    continue
                ch = raw[i]
                if ch == "_":
                    if buf:
                        segments.append((''.join(buf), bold, italic))
                        buf.clear()
                    italic = not italic
                    i += 1
                    continue
                buf.append(ch)
                i += 1
            if buf:
                segments.append((''.join(buf), bold, italic))
            if not segments:
                segments.append((" ", line_start_bold, line_start_italic))
            parsed.append(segments)
        return parsed

    def _render_node_text(self, nid: int) -> None:
        items = self.canvas_items.get(nid)
        if not items:
            return
        for tid in items.get("texts", []) or []:
            self.item_to_node.pop(tid, None)
            self.canvas.delete(tid)
        items["texts"] = []
        node = self.nodes[nid]
        parsed = self._parse_formatted_lines(node.get("text", ""))

        x0, y0, x1, y1 = self._node_bbox(nid)
        padding_top = 12
        current_y = y0 + padding_top
        for line in parsed:
            sanitized = [(segment or " ", bold, italic) for segment, bold, italic in line] if line else [(" ", False, False)]
            line_height = max(self._get_font_variant(bold, italic).metrics("linespace") for _, bold, italic in sanitized)
            total_width = sum(self._get_font_variant(bold, italic).measure(segment) for segment, bold, italic in sanitized)
            start_x = (x0 + x1) / 2 - total_width / 2
            cursor_x = start_x
            for segment_text, bold, italic in sanitized:
                font = self._get_font_variant(bold, italic)
                text_id = self.canvas.create_text(
                    cursor_x,
                    current_y + line_height / 2,
                    text=segment_text,
                    font=font,
                    anchor="w",
                    tags=("node", "node-text"),
                )
                self.item_to_node[text_id] = nid
                self.canvas.tag_bind(text_id, "<Button-1>", lambda e, n=nid: self.on_click_node(e, n))
                self.canvas.tag_bind(text_id, "<Double-Button-1>", lambda e, n=nid: self.on_double_click_node(e, n))
                self.canvas.tag_bind(text_id, "<Button-3>", lambda e, n=nid: self.on_node_context(e, n))
                self.canvas.tag_raise(text_id, items["shape"])
                items["texts"].append(text_id)
                cursor_x += font.measure(segment_text)
            current_y += line_height + 4
        if not items["texts"]:
            font = self._get_font_variant(False, False)
            text_id = self.canvas.create_text(
                (x0 + x1) / 2,
                (y0 + y1) / 2,
                text=" ",
                font=font,
                tags=("node", "node-text"),
            )
            self.item_to_node[text_id] = nid
            self.canvas.tag_bind(text_id, "<Button-1>", lambda e, n=nid: self.on_click_node(e, n))
            self.canvas.tag_bind(text_id, "<Double-Button-1>", lambda e, n=nid: self.on_double_click_node(e, n))
            self.canvas.tag_bind(text_id, "<Button-3>", lambda e, n=nid: self.on_node_context(e, n))
            self.canvas.tag_raise(text_id, items["shape"])
            items["texts"].append(text_id)

    def _compute_vertical_slots(
        self,
        root_id: int,
        directions: Dict[int, int],
        depths: Dict[int, int],
    ) -> Dict[int, float]:
        slots: Dict[int, float] = {root_id: 0.0}
        levels: Dict[int, List[int]] = {}
        for nid, depth in depths.items():
            levels.setdefault(depth, []).append(nid)
        max_depth = max(levels.keys(), default=0)
        for depth in range(1, max_depth + 1):
            nodes = levels.get(depth, [])
            if not nodes:
                continue
            left: List[Tuple[float, int, int, Optional[int]]] = []
            right: List[Tuple[float, int, int, Optional[int]]] = []
            centre: List[Tuple[float, int, int, Optional[int]]] = []
            for nid in nodes:
                parent_id = self.parent.get(nid)
                parent_slot = slots.get(parent_id, 0.0)
                try:
                    ordinal = self.nodes[parent_id]["children"].index(nid) if parent_id is not None else 0
                except ValueError:
                    ordinal = 0
                direction = directions.get(nid, directions.get(parent_id, 0))
                entry = (parent_slot, ordinal, nid, parent_id)
                if direction > 0:
                    right.append(entry)
                elif direction < 0:
                    left.append(entry)
                else:
                    centre.append(entry)
            max_side = max(len(left), len(right))
            side_positions = self._symmetrical_positions(max_side)
            centre_positions = self._symmetrical_positions(len(centre))

            def assign(entries: List[Tuple[float, int, int, Optional[int]]], positions: List[float]) -> None:
                if not entries:
                    return
                ordered = sorted(entries, key=lambda item: (item[0], item[1]))
                length = len(positions)
                for idx, (parent_slot, _, nid, parent_id) in enumerate(ordered):
                    base = positions[min(idx, length - 1)] if length else 0.0
                    weight = 0.0 if parent_id in (None, root_id) else 0.25
                    slot = base * (1 - weight) + parent_slot * weight
                    slots[nid] = slot

            assign(left, side_positions)
            assign(right, side_positions)
            assign(centre, centre_positions)
        for nid in self.nodes:
            slots.setdefault(nid, 0.0)
        return slots

    def _edge_control_points(
        self,
        pid: int,
        cid: int,
        start: Tuple[float, float],
        end: Tuple[float, float],
        extra_lateral: float = 0.0,
    ) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        sx, sy = start
        ex, ey = end
        dx = ex - sx
        dy = ey - sy
        dist = max(math.hypot(dx, dy), 1.0)
        siblings = self.nodes[pid]["children"]
        if len(siblings) > 1 and cid in siblings:
            idx = siblings.index(cid)
            centre = (len(siblings) - 1) / 2
            spread = idx - centre
        else:
            spread = 0.0
        scale = self.ws.scale or 1.0
        smoothing = min(1.0, max(0.25, dist / (NODE_W * scale * 1.25)))
        lateral = spread * NODE_H * scale * 0.32 * smoothing
        nx, ny = dx / dist, dy / dist
        tx, ty = -ny, nx
        base_pull = min(max(dist * 0.22, NODE_W * scale * 0.3), NODE_W * scale * 1.05)
        base_pull *= 0.75 + smoothing * 0.55
        if dist < NODE_W * scale * 0.75:
            base_pull = dist * 0.3
            lateral *= 0.4
        lateral += extra_lateral
        cp1 = [sx + nx * base_pull + tx * lateral, sy + ny * base_pull + ty * lateral]
        cp2 = [ex - nx * base_pull + tx * lateral, ey - ny * base_pull + ty * lateral]

        max_dim = max(NODE_W, NODE_H) * scale
        safety = max_dim * 0.5
        node_radius = math.hypot(NODE_W * scale / 2, NODE_H * scale / 2) + NODE_MARGIN * scale
        for other_id in self.nodes:
            if other_id in (pid, cid):
                continue
            ox, oy = self._node_center(other_id)
            seg_len_sq = max(dist ** 2, 1.0)
            t = ((ox - sx) * dx + (oy - sy) * dy) / seg_len_sq
            if t <= 0 or t >= 1:
                continue
            closest_x = sx + dx * t
            closest_y = sy + dy * t
            vec_x = closest_x - ox
            vec_y = closest_y - oy
            separation = math.hypot(vec_x, vec_y)
            clearance = separation - node_radius
            if clearance >= safety:
                continue
            influence = max(0.0, min(1.0, (safety - clearance) / safety)) * smoothing
            push_dir_x = (vec_x / separation) if separation else tx
            push_dir_y = (vec_y / separation) if separation else ty
            push_mag = min(influence * (node_radius * 0.45 + dist * 0.18), dist * 0.4)
            push_x = push_dir_x * push_mag
            push_y = push_dir_y * push_mag
            w1 = (1 - t) ** 1.3
            w2 = t ** 1.3
            total = w1 + w2
            if total:
                w1 /= total
                w2 /= total
            cp1[0] += push_x * w1
            cp1[1] += push_y * w1
            cp2[0] += push_x * w2
            cp2[1] += push_y * w2

        max_perp = max(NODE_H * scale * (0.4 * smoothing + 0.18), dist * 0.22)
        min_along = dist * 0.1
        max_along = dist - min_along
        def clamp_point(point: List[float]) -> List[float]:
            rel_x = point[0] - sx
            rel_y = point[1] - sy
            along = max(min_along, min(max_along, rel_x * nx + rel_y * ny))
            perp = rel_x * tx + rel_y * ty
            if abs(perp) > max_perp:
                perp = math.copysign(max_perp, perp)
            point[0] = sx + nx * along + tx * perp
            point[1] = sy + ny * along + ty * perp
            return point

        cp1 = clamp_point(cp1)
        cp2 = clamp_point(cp2)

        min_offset = NODE_H * scale * 0.1 + 3

        def orient(base_sign: float) -> Tuple[List[float], List[float], float]:
            total_adjust = 0.0
            points = []
            for point in (cp1[:], cp2[:]):
                signed_distance = ((point[0] - sx) * dy - (point[1] - sy) * dx) / dist
                desired = base_sign if base_sign else math.copysign(1.0, signed_distance or lateral or 1.0)
                if signed_distance * desired < min_offset:
                    delta = min_offset - signed_distance * desired
                    point[0] += tx * desired * delta
                    point[1] += ty * desired * delta
                    signed_distance = ((point[0] - sx) * dy - (point[1] - sy) * dx) / dist
                    total_adjust += delta
                points.append(point)
            return points[0], points[1], total_adjust

        cp1_pos, cp2_pos, adjust_pos = orient(1.0)
        cp1_neg, cp2_neg, adjust_neg = orient(-1.0)
        bias = 0.04 if lateral >= 0 else -0.04
        if adjust_pos + max(0.0, -bias) <= adjust_neg + max(0.0, bias):
            cp1, cp2 = cp1_pos, cp2_pos
        else:
            cp1, cp2 = cp1_neg, cp2_neg

        return (cp1[0], cp1[1]), (cp2[0], cp2[1])

    def _has_obstacle_between(
        self,
        pid: int,
        cid: int,
        start: Tuple[float, float],
        end: Tuple[float, float],
    ) -> bool:
        sx, sy = start
        ex, ey = end
        dx = ex - sx
        dy = ey - sy
        dist_sq = dx * dx + dy * dy
        if dist_sq < 1e-3:
            return False
        scale = self.ws.scale or 1.0
        node_radius = math.hypot(NODE_W * scale / 2, NODE_H * scale / 2) + NODE_MARGIN * scale
        buffer = max(6.0, NODE_H * scale * 0.25)
        for other_id in self.nodes:
            if other_id in (pid, cid):
                continue
            ox, oy = self._node_center(other_id)
            t = ((ox - sx) * dx + (oy - sy) * dy) / dist_sq
            if t <= 0 or t >= 1:
                continue
            closest_x = sx + t * dx
            closest_y = sy + t * dy
            separation = math.hypot(closest_x - ox, closest_y - oy)
            if separation < node_radius + buffer:
                return True
        return False

    def on_node_context(self, event: tk.Event, nid: int) -> None:
        self._hide_color_palette()
        if nid not in self.selected_ids:
            self._select(nid)
        self._context_node = nid
        self._show_color_palette(event.x_root, event.y_root)

    def on_canvas_context(self, event: tk.Event) -> None:
        self._hide_color_palette()
        if self.selected_ids:
            self._context_node = None
            self._show_color_palette(event.x_root, event.y_root)
            return
        nid = self._node_at(event.x, event.y)
        if nid is None:
            return
        self._select(nid)
        self._context_node = nid
        self._show_color_palette(event.x_root, event.y_root)

    def _show_color_palette(self, x: int, y: int) -> None:
        self._hide_color_palette()
        window = tk.Toplevel(self.root)
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        cols = max(1, self._palette_cols)
        frame = tk.Frame(window, bg="#f4f4f5", bd=1, relief="solid")
        frame.pack(padx=2, pady=2)
        for idx, color in enumerate(self._color_palette):
            btn = tk.Button(
                frame,
                bg=color,
                activebackground=color,
                width=2,
                height=1,
                relief="flat",
                command=lambda c=color: self._apply_node_color(c),
            )
            btn.grid(row=idx // cols, column=idx % cols, padx=2, pady=2)
        reset_btn = tk.Button(frame, text="Reset", command=self._reset_node_color, width=cols * 2)
        reset_btn.grid(row=(len(self._color_palette) + cols - 1) // cols, column=0, columnspan=cols, pady=(4, 0))
        window.update_idletasks()
        window.geometry(f"+{int(x)}+{int(y)}")
        window.deiconify()
        window.bind("<FocusOut>", lambda _e: self._hide_color_palette())
        window.focus_force()
        self._palette_window = window

    def _hide_color_palette(self) -> None:
        if self._palette_window is not None:
            try:
                self._palette_window.destroy()
            except tk.TclError:
                pass
            self._palette_window = None

    def _apply_node_color(self, color: str) -> None:
        targets = set(self.selected_ids)
        if not targets and self._context_node is not None:
            targets = {self._context_node}
        if not targets:
            return
        for nid in targets:
            if nid not in self.nodes:
                continue
            self.nodes[nid]["fill"] = color
            self.nodes[nid]["custom"] = True
            self._update_node_fill(nid)
        self._set_status(f"Color applied to {len(targets)} node(s).")
        self._context_node = None
        self._hide_color_palette()

    def _reset_node_color(self) -> None:
        targets = set(self.selected_ids)
        if not targets and self._context_node is not None:
            targets = {self._context_node}
        if not targets:
            return
        for nid in targets:
            if nid not in self.nodes:
                continue
            depth = self._node_depth(nid)
            self.nodes[nid]["fill"] = self._default_fill_for_depth(depth)
            self.nodes[nid]["custom"] = False
            self._update_node_fill(nid)
        self._set_status(f"Reset color for {len(targets)} node(s).")
        self._context_node = None
        self._hide_color_palette()
    def redraw(self) -> None:
        self._refresh_all_positions()
        self.canvas.delete("edge")
        edges = list(self._edges())
        valid_keys = set(edges)
        for key in list(self.ws.edge_offsets.keys()):
            if key not in valid_keys:
                self.ws.edge_offsets.pop(key, None)
        drawn_paths: List[Dict[str, Any]] = []
        for pid, cid in edges:
            self._render_edge(pid, cid, drawn_paths)
        self.canvas.tag_lower("edge")
        self._highlight_selection()

    def redraw_edges_of_node_and_neighbors(self, nid: int) -> None:
        self.redraw()

    def _render_edge(
        self,
        pid: int,
        cid: int,
        drawn_paths: List[Dict[str, Any]],
    ) -> None:
        px, py = self._node_center(pid)
        cx, cy = self._node_center(cid)
        start = self._edge_exit_point(pid, cx, cy)
        end = self._edge_exit_point(cid, px, py)
        if abs(start[0] - end[0]) + abs(start[1] - end[1]) < 6:
            start = (start[0] * 0.9 + px * 0.1, start[1] * 0.9 + py * 0.1)
            end = (end[0] * 0.9 + cx * 0.1, end[1] * 0.9 + cy * 0.1)
        base_offset = self.ws.edge_offsets.get((pid, cid), 0.0)
        candidates = self._edge_offset_candidates(base_offset)
        chosen_points: Optional[List[Tuple[float, float]]] = None
        chosen_offset = base_offset
        for offset in candidates:
            cp1, cp2 = self._edge_control_points(pid, cid, start, end, offset)
            points = self._sample_edge_points(start, cp1, cp2, end)
            if not self._path_intersects(points, drawn_paths, start, end):
                chosen_points = points
                chosen_offset = offset
                break
        if chosen_points is None:
            fallback_offset = candidates[-1]
            cp1, cp2 = self._edge_control_points(pid, cid, start, end, fallback_offset)
            chosen_points = self._sample_edge_points(start, cp1, cp2, end)
            chosen_offset = fallback_offset
        self.ws.edge_offsets[(pid, cid)] = chosen_offset
        flat = [coord for point in chosen_points for coord in point]
        self.canvas.create_line(
            *flat,
            fill=EDGE_COLOR,
            width=2,
            smooth=True,
            splinesteps=32,
            tags="edge",
        )
        drawn_paths.append({"points": chosen_points, "start": start, "end": end})

    def _edge_offset_candidates(self, base: float) -> List[float]:
        steps = [0.0, 20.0, -20.0, 40.0, -40.0, 60.0, -60.0, 80.0, -80.0]
        offsets: List[float] = []
        for step in steps:
            candidate = base + step
            if not offsets or abs(offsets[-1] - candidate) > 1e-6:
                offsets.append(candidate)
        return offsets

    def _sample_edge_points(
        self,
        start: Tuple[float, float],
        cp1: Tuple[float, float],
        cp2: Tuple[float, float],
        end: Tuple[float, float],
        steps: int = 32,
    ) -> List[Tuple[float, float]]:
        if steps < 2:
            steps = 2
        points: List[Tuple[float, float]] = []
        for i in range(steps + 1):
            t = i / steps
            mt = 1.0 - t
            x = (mt ** 3) * start[0] + 3 * (mt ** 2) * t * cp1[0] + 3 * mt * (t ** 2) * cp2[0] + (t ** 3) * end[0]
            y = (mt ** 3) * start[1] + 3 * (mt ** 2) * t * cp1[1] + 3 * mt * (t ** 2) * cp2[1] + (t ** 3) * end[1]
            points.append((x, y))
        return points

    def _path_intersects(
        self,
        points: List[Tuple[float, float]],
        existing: List[Dict[str, Any]],
        start: Tuple[float, float],
        end: Tuple[float, float],
    ) -> bool:
        for info in existing:
            if self._shares_endpoint(start, end, info["start"], info["end"]):
                continue
            if self._paths_cross(points, info["points"]):
                return True
        return False

    def _shares_endpoint(
        self,
        start_a: Tuple[float, float],
        end_a: Tuple[float, float],
        start_b: Tuple[float, float],
        end_b: Tuple[float, float],
        tol: float = 6.0,
    ) -> bool:
        return (
            self._points_close(start_a, start_b, tol)
            or self._points_close(start_a, end_b, tol)
            or self._points_close(end_a, start_b, tol)
            or self._points_close(end_a, end_b, tol)
        )

    def _paths_cross(
        self,
        a_points: List[Tuple[float, float]],
        b_points: List[Tuple[float, float]],
    ) -> bool:
        for seg_a_start, seg_a_end in zip(a_points, a_points[1:]):
            for seg_b_start, seg_b_end in zip(b_points, b_points[1:]):
                if self._segments_share_endpoint(seg_a_start, seg_a_end, seg_b_start, seg_b_end):
                    continue
                if self._segments_intersect(seg_a_start, seg_a_end, seg_b_start, seg_b_end):
                    return True
        return False

    def _segments_share_endpoint(
        self,
        a_start: Tuple[float, float],
        a_end: Tuple[float, float],
        b_start: Tuple[float, float],
        b_end: Tuple[float, float],
        tol: float = 1.5,
    ) -> bool:
        return (
            self._points_close(a_start, b_start, tol)
            or self._points_close(a_start, b_end, tol)
            or self._points_close(a_end, b_start, tol)
            or self._points_close(a_end, b_end, tol)
        )

    def _points_close(
        self,
        a: Tuple[float, float],
        b: Tuple[float, float],
        tol: float = 0.5,
    ) -> bool:
        return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol

    def _segments_intersect(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        q1: Tuple[float, float],
        q2: Tuple[float, float],
    ) -> bool:
        def orientation(a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float]) -> float:
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

        def on_segment(a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float]) -> bool:
            return (
                min(a[0], c[0]) - 1e-6 <= b[0] <= max(a[0], c[0]) + 1e-6
                and min(a[1], c[1]) - 1e-6 <= b[1] <= max(a[1], c[1]) + 1e-6
            )

        o1 = orientation(p1, p2, q1)
        o2 = orientation(p1, p2, q2)
        o3 = orientation(q1, q2, p1)
        o4 = orientation(q1, q2, p2)
        tol = 1e-6
        if (o1 > tol and o2 < -tol) or (o1 < -tol and o2 > tol):
            if (o3 > tol and o4 < -tol) or (o3 < -tol and o4 > tol):
                return True
        if abs(o1) <= tol and on_segment(p1, q1, p2):
            return True
        if abs(o2) <= tol and on_segment(p1, q2, p2):
            return True
        if abs(o3) <= tol and on_segment(q1, p1, q2):
            return True
        if abs(o4) <= tol and on_segment(q1, p2, q2):
            return True
        return False

    def _collect_subtree(self, nid: int) -> Iterable[int]:
        collected: List[int] = []

        def dfs(node_id: int) -> None:
            collected.append(node_id)
            for child in self.nodes[node_id]["children"]:
                dfs(child)

        dfs(nid)
        return collected

    def _subtree_size(self, nid: int) -> int:
        return len(self._collect_subtree(nid))
    # ---------- Event handlers ----------
    def on_click(self, event: tk.Event) -> None:
        self._hide_color_palette()
        current = self.canvas.find_withtag("current")
        if current and current[0] in self.item_to_node:
            return
        self._select(None)
        self.dragging = {
            "mode": "pan",
            "id": None,
            "dx": 0.0,
            "dy": 0.0,
            "start_x": event.x,
            "start_y": event.y,
            "offset_x": self.ws.offset_x,
            "offset_y": self.ws.offset_y,
        }
        self._set_status("Drag to pan the workspace.")

    def on_double_click(self, event: tk.Event) -> Optional[str]:
        self._hide_color_palette()
        if self._node_at(event.x, event.y) is not None:
            return "break"
        if not self.nodes:
            lx, ly = self._from_canvas_point(event.x, event.y)
            nid = self._create_node("Root", lx, ly, depth=0)
            self._set_root(nid)
            self._select(nid)
            self._set_status("Root created.")
            return "break"
        target = self.selected_id or self.root_id
        if target is not None:
            self._select(target)
            self.add_child()
            return "break"
        return "break"

    def on_click_node(self, event: tk.Event, nid: int) -> None:
        self._hide_color_palette()
        additive = bool(event.state & 0x0004)
        self._select(nid, additive=additive)
        lx, ly = self._from_canvas_point(event.x, event.y)
        node = self.nodes[nid]
        self.dragging = {
            "mode": "node",
            "id": nid,
            "dx": lx - node["x"],
            "dy": ly - node["y"],
            "start_x": event.x,
            "start_y": event.y,
            "offset_x": 0.0,
            "offset_y": 0.0,
        }

    def on_double_click_node(self, event: tk.Event, nid: int) -> None:
        self._hide_color_palette()
        self._select(nid)
        self.edit_selected()
        return "break"

    def on_drag(self, event: tk.Event) -> None:
        mode = self.dragging.get("mode") if self.dragging else None
        if mode == "node":
            nid = self.dragging.get("id")
            if not nid:
                return
            lx, ly = self._from_canvas_point(event.x, event.y)
            self.nodes[nid]["x"] = lx - float(self.dragging.get("dx", 0.0))
            self.nodes[nid]["y"] = ly - float(self.dragging.get("dy", 0.0))
            self._refresh_node_position(nid)
            self.redraw_edges_of_node_and_neighbors(nid)
        elif mode == "pan":
            start_x = float(self.dragging.get("start_x", event.x))
            start_y = float(self.dragging.get("start_y", event.y))
            base_x = float(self.dragging.get("offset_x", self.ws.offset_x))
            base_y = float(self.dragging.get("offset_y", self.ws.offset_y))
            self.ws.offset_x = base_x + (event.x - start_x)
            self.ws.offset_y = base_y + (event.y - start_y)
            self.canvas.config(cursor="fleur")
            self.redraw()

    def on_release(self, event: tk.Event) -> None:
        if self.dragging.get("mode") == "pan":
            self.canvas.config(cursor="")
        self.dragging = {
            "mode": None,
            "id": None,
            "dx": 0.0,
            "dy": 0.0,
            "start_x": 0.0,
            "start_y": 0.0,
            "offset_x": 0.0,
            "offset_y": 0.0,
        }

    def _on_ctrl_wheel(self, event: tk.Event) -> None:
        factor = ZOOM_STEP if event.delta > 0 else 1 / ZOOM_STEP
        self.zoom(factor, origin=(event.x, event.y))

    def _on_wheel_scroll(self, event: tk.Event) -> None:
        delta = (event.delta // 120) * PAN_STEP
        self.pan_by(0, delta)

    # ---------- View transforms ----------
    def pan_by(self, dx: float, dy: float) -> None:
        self.ws.offset_x += dx
        self.ws.offset_y += dy
        self.redraw()

    def zoom(self, factor: float, origin: Optional[Tuple[float, float]] = None) -> None:
        ws = self.ws
        old_scale = ws.scale
        new_scale = max(ZOOM_MIN, min(ZOOM_MAX, old_scale * factor))
        if abs(new_scale - old_scale) < 1e-3:
            return
        if origin is None:
            origin = (
                self.canvas.winfo_width() / 2,
                self.canvas.winfo_height() / 2,
            )
        cx, cy = origin
        scale_ratio = new_scale / old_scale if old_scale else 1.0
        ws.offset_x = cx - scale_ratio * (cx - ws.offset_x)
        ws.offset_y = cy - scale_ratio * (cy - ws.offset_y)
        ws.scale = new_scale
        self.redraw()
        self._set_status(f"Zoom {int(ws.scale * 100)}%")

    def reset_view(self) -> None:
        self.ws.scale = 1.0
        self.ws.offset_x = 0.0
        self.ws.offset_y = 0.0
        self.redraw()
        self._set_status("View reset.")
    # ---------- Save / Load ----------
    def _load_data_into_current_workspace(self, data: dict) -> None:
        self.canvas.delete("all")
        self.ws.edge_offsets.clear()
        self.ws.palette_index = 0
        self.nodes.clear()
        self.parent.clear()
        self.canvas_items.clear()
        self.item_to_node.clear()
        self.dragging = {
            "mode": None,
            "id": None,
            "dx": 0.0,
            "dy": 0.0,
            "start_x": 0.0,
            "start_y": 0.0,
            "offset_x": 0.0,
            "offset_y": 0.0,
        }
        self.ws.scale = 1.0
        self.ws.offset_x = 0.0
        self.ws.offset_y = 0.0

        raw_nodes = data.get("nodes", {})
        max_id = 0
        for nid_str, nd in raw_nodes.items():
            nid = int(nid_str)
            max_id = max(max_id, nid)
            self.nodes[nid] = {
                "text": nd.get("text", ""),
                "x": nd.get("x", 0.0),
                "y": nd.get("y", 0.0),
                "children": list(nd.get("children", [])),
                "fill": nd.get("fill"),
                "custom": bool(nd.get("custom", False)),
            }
            self.parent[nid] = None
        for pid, info in self.nodes.items():
            for cid in info["children"]:
                self.parent[cid] = pid

        self.root_id = data.get("root")
        fallback_next = max_id + 1
        provided_next = data.get("next_id", fallback_next)
        self.next_id = max(provided_next, fallback_next)

        self.ws.palette_index = len(self.nodes)
        for nid in self.nodes:
            shape, txt = self._draw_node(nid)
            self.canvas_items[nid] = {"shape": shape, "texts": txt}

        if self.root_id not in self.nodes:
            self.root_id = next(iter(self.nodes), None)

        self.redraw()
        self._refresh_level_panel()
        if self.root_id:
            self._select(self.root_id)
        else:
            self._select(None)

    def save(self) -> None:
        if not self.nodes:
            messagebox.showinfo("Save", "No nodes to save.")
            return
        initialdir = ""
        initialfile = ""
        if self.current_path:
            current = Path(self.current_path)
            initialdir = str(current.parent)
            initialfile = current.name
        else:
            initialfile = f"{self.ws.name}.json"
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            title="Save Mind Map",
            initialdir=initialdir,
            initialfile=initialfile,
        )
        if not path:
            return
        data = {
            "root": self.root_id,
            "next_id": self.next_id,
            "nodes": {
                str(nid): {
                    "text": nd["text"],
                    "x": nd["x"],
                    "y": nd["y"],
                    "children": nd["children"],
                    "fill": nd.get("fill"),
                    "custom": nd.get("custom", False),
                }
                for nid, nd in self.nodes.items()
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.current_path = path
        self._rename_workspace(self.ws, Path(path).stem or self.ws.name)
        self._set_status(f"Saved to {path}.")

    def load(self) -> None:
        path = filedialog.askopenfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            title="Load Mind Map",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return

        name = Path(path).stem or None
        workspace = self._create_workspace(name=name or None, path=path)
        self._load_data_into_current_workspace(data)
        if name:
            self._rename_workspace(workspace, name)
        self.current_path = path
        self._set_status(f"Loaded {path}.")

    # ---------- Layout ----------
    def _assign_directions(self, root_id: int) -> Dict[int, int]:
        directions: Dict[int, int] = {root_id: 0}
        children = self.nodes[root_id]["children"]
        for index, child in enumerate(children):
            directions[child] = -1 if index % 2 == 0 else 1
        queue = list(children)
        while queue:
            nid = queue.pop(0)
            direction = directions.get(nid, 1)
            for child in self.nodes[nid]["children"]:
                directions[child] = direction
                queue.append(child)
        for nid in self.nodes:
            directions.setdefault(nid, 1 if nid != root_id else 0)
        return directions

    def _compute_depths(self, root_id: int) -> Dict[int, int]:
        depths: Dict[int, int] = {root_id: 0}
        stack = [root_id]
        while stack:
            nid = stack.pop()
            for child in self.nodes[nid]["children"]:
                depths[child] = depths[nid] + 1
                stack.append(child)
        for nid in self.nodes:
            if nid not in depths:
                parent_id = self.parent.get(nid)
                depths[nid] = depths.get(parent_id, 0) + 1 if parent_id is not None else 0
        return depths

    def auto_layout(self) -> None:
        if not self.nodes:
            return
        root_id = self.root_id or next(iter(self.nodes))
        self.canvas.update_idletasks()
        cx_canvas = max(self.canvas.winfo_width(), NODE_W * 2) / 2
        cy_canvas = max(self.canvas.winfo_height(), NODE_H * 2) / 2
        base_x, base_y = self._from_canvas_point(cx_canvas, cy_canvas)

        directions = self._assign_directions(root_id)
        depths = self._compute_depths(root_id)
        slots = self._compute_vertical_slots(root_id, directions, depths)
        root_slot = slots.get(root_id, 0.0)

        for nid in self.nodes:
            direction = directions.get(nid, 1 if nid != root_id else 0)
            depth = depths.get(nid, 0)
            if direction < 0:
                x = base_x - depth * (NODE_W + HORIZ_GAP)
            elif direction > 0:
                x = base_x + depth * (NODE_W + HORIZ_GAP)
            else:
                x = base_x
            offset = slots.get(nid, root_slot) - root_slot
            y = base_y + offset * (NODE_H + VERT_GAP)
            self.nodes[nid]["x"] = x
            self.nodes[nid]["y"] = y
            if not self.nodes[nid].get("custom"):
                self.nodes[nid]["fill"] = self._default_fill_for_depth(depth)
                self._update_node_fill(nid)

        self.redraw()
        self._refresh_level_panel()
        self._set_status("Auto layout applied.")

    # ---------- Placement helpers ----------
    def _find_free_position(self, x: float, y: float) -> Tuple[float, float]:
        if self._is_position_free(x, y):
            return x, y
        step_x = NODE_W + HORIZ_GAP
        step_y = NODE_H + VERT_GAP
        for radius in range(1, 9):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if abs(dx) != radius and abs(dy) != radius:
                        continue
                    candidate_x = x + dx * step_x
                    candidate_y = y + dy * step_y
                    if self._is_position_free(candidate_x, candidate_y):
                        return candidate_x, candidate_y
        return x + 10 * step_x, y + 10 * step_y

    def _is_position_free(self, x: float, y: float) -> bool:
        if not self.nodes:
            return True
        threshold_x = NODE_W + NODE_MARGIN
        threshold_y = NODE_H + NODE_MARGIN
        for node in self.nodes.values():
            if abs(x - node["x"]) < threshold_x and abs(y - node["y"]) < threshold_y:
                return False
        return True

    # ---------- Window ----------
    def _update_title(self) -> None:
        if not self._current_ws:
            self.root.title("Mind Map")
            return
        root_name = self.nodes.get(self.root_id, {}).get("text", "None") if self.root_id else "None"
        self.root.title(f"Mind Map - {self.ws.name} - Root: {root_name}")

def main() -> None:
    root = tk.Tk()
    app = MindMapApp(root)
    root.minsize(900, 600)
    root.mainloop()


if __name__ == "__main__":
    main()




