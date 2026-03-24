"""
拼豆豆仓管理工具 v1.8 (Multi-Image Support)
依赖：Python 3.8+ 标准库, Pillow
新增：
  1. 多图支持：补货和作品记录均可上传多张图片。
  2. 存储优化：数据库图片字段改为 JSON 列表存储。
  3. 查看器升级：支持缩略图网格浏览和点击放大预览。
  4. 编辑器升级：支持在编辑日志时增删单张图片。
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import sqlite3, csv, json, os, shutil
from datetime import datetime
import re

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("警告: 未检测到 Pillow 库，图片功能将不可用。")

# ── 配置与全局变量 ──────────────────────────────────────────────────────────
CONFIG_FILE = "beads_config.json"
DB_FILE_DEFAULT = "beads.db"
IMG_FOLDER = "projects_images"

if not os.path.exists(IMG_FOLDER):
    os.makedirs(IMG_FOLDER)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "categories": {"A": "A 暖黄", "B": "B 绿色", "H": "H 黑白"},
            "category_order": ["A", "B", "H"],
            "colors": [["A1","#faf5cd"], ["H1","#ffffff"], ["H7","#000000"]],
            "ui_settings": {"card_width": 74, "card_height": 82, "card_gap": 6, "db_file": DB_FILE_DEFAULT}
        }
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, ensure_ascii=False, indent=2)
        except: pass
        return default_config
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        messagebox.showerror("配置错误", f"配置文件格式错误：\n{e}")
        raise

try:
    CONFIG = load_config()
    RAW = [tuple(item) for item in CONFIG.get("colors", [])]
    CAT_NAMES = CONFIG.get("categories", {})
    CAT_ORDER = CONFIG.get("category_order", list(CAT_NAMES.keys()))
    UI_SETTINGS = CONFIG.get("ui_settings", {})
    CARD_W = UI_SETTINGS.get("card_width", 74)
    CARD_H = UI_SETTINGS.get("card_height", 82)
    CARD_GAP = UI_SETTINGS.get("card_gap", 6)
    DB_FILE = UI_SETTINGS.get("db_file", DB_FILE_DEFAULT)
except Exception:
    RAW, CAT_NAMES, CAT_ORDER = [], {}, []
    CARD_W, CARD_H, CARD_GAP = 74, 82, 6
    DB_FILE = DB_FILE_DEFAULT

SORT_MODE = 'code' 

# ── 工具函数 ──────────────────────────────────────────────────────────────────
def fg_for(hx: str) -> str:
    if not hx: return "#000000"
    h = hx.lstrip("#")
    if len(h) != 6: return "#000000"
    try:
        r, g, b = int(h[:2],16), int(h[2:4],16), int(h[4:6],16)
        return "#000000" if (.299*r + .587*g + .114*b) > 128 else "#ffffff"
    except ValueError: return "#000000"

def cat_of(c): return "".join(x for x in c if x.isalpha())
def num_of(c):
    n = "".join(x for x in c if x.isdigit())
    return int(n) if n else 0

def sort_key(d):
    global SORT_MODE
    if SORT_MODE == 'qty':
        return (d["qty"], cat_of(d["code"]), num_of(d["code"]))
    else:
        return (CAT_ORDER.index(d["cat"]) if d["cat"] in CAT_ORDER else 99, num_of(d["code"]))

# ── 数据库层 (升级支持 JSON 图片列表) ───────────────────────────────────────
class BeadDB:
    def __init__(self, path=DB_FILE):
        self.path = path; self._init()
    def _conn(self): return sqlite3.connect(self.path)
    
    def _init(self):
        with self._conn() as cx:
            cx.execute("""CREATE TABLE IF NOT EXISTS beads(
                code TEXT PRIMARY KEY, hex TEXT, category TEXT,
                qty INTEGER DEFAULT 0, threshold INTEGER DEFAULT 50,
                notes TEXT DEFAULT '', updated TEXT)""")
            
            cx.execute("""CREATE TABLE IF NOT EXISTS history(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT, old_qty INTEGER, new_qty INTEGER, 
                ts TEXT, project_name TEXT DEFAULT '', notes TEXT DEFAULT '', 
                image_data TEXT DEFAULT '[]', type TEXT DEFAULT 'deduct', price REAL DEFAULT 0)""")
            
            # 兼容旧版迁移：将旧的 image_path (string) 转为 image_data (json list)
            cols = [col[1] for col in cx.execute("PRAGMA table_info(history)").fetchall()]
            if 'image_data' not in cols:
                # 如果有旧列 image_path
                if 'image_path' in cols:
                    cx.execute("ALTER TABLE history ADD COLUMN image_data TEXT DEFAULT '[]'")
                    # 迁移数据
                    cx.execute("UPDATE history SET image_data = json_array(image_path) WHERE image_path IS NOT NULL AND image_path != ''")
                    cx.execute("ALTER TABLE history DROP COLUMN image_path")
                else:
                    cx.execute("ALTER TABLE history ADD COLUMN image_data TEXT DEFAULT '[]'")
            
            if 'type' not in cols:
                cx.execute("ALTER TABLE history ADD COLUMN type TEXT DEFAULT 'deduct'")
            if 'price' not in cols:
                cx.execute("ALTER TABLE history ADD COLUMN price REAL DEFAULT 0")

            now = datetime.now().isoformat()
            for code, hex_ in RAW:
                cx.execute("INSERT OR IGNORE INTO beads(code,hex,category,qty,threshold,notes,updated)"
                           " VALUES(?,?,?,0,50,'',?)", (code, hex_, cat_of(code), now))

    def get_all(self):
        with self._conn() as cx:
            rows = cx.execute("SELECT code,hex,category,qty,threshold,notes FROM beads").fetchall()
        return [{"code":r[0],"hex":r[1],"cat":r[2],"qty":r[3],"threshold":r[4],"notes":r[5]} for r in rows]

    def get_one(self, code):
        with self._conn() as cx:
            r = cx.execute("SELECT code,hex,category,qty,threshold,notes FROM beads WHERE code=?", (code,)).fetchone()
        return {"code":r[0],"hex":r[1],"cat":r[2],"qty":r[3],"threshold":r[4],"notes":r[5]} if r else None

    def stats(self):
        with self._conn() as cx:
            total  = cx.execute("SELECT COUNT(*) FROM beads").fetchone()[0]
            sumqty = cx.execute("SELECT SUM(qty) FROM beads").fetchone()[0] or 0
            low    = cx.execute("SELECT COUNT(*) FROM beads WHERE qty>0 AND qty<=threshold").fetchone()[0]
            zero   = cx.execute("SELECT COUNT(*) FROM beads WHERE qty=0").fetchone()[0]
        return {"total":total,"sum_qty":sumqty,"low":low,"zero":zero}

    def get_lowest(self, limit=3):
        with self._conn() as cx:
            return cx.execute("SELECT code, qty FROM beads ORDER BY qty ASC, code ASC LIMIT ?", (limit,)).fetchall()

    def get_history_logs(self, code=None, limit=200):
        with self._conn() as cx:
            if code:
                sql = """SELECT id, code, old_qty, new_qty, ts, project_name, notes, image_data, type, price 
                         FROM history WHERE code=? ORDER BY id DESC LIMIT ?"""
                rows = cx.execute(sql, (code, limit)).fetchall()
            else:
                sql = """SELECT id, code, old_qty, new_qty, ts, project_name, notes, image_data, type, price 
                         FROM history ORDER BY id DESC LIMIT ?"""
                rows = cx.execute(sql, (limit,)).fetchall()
        logs = []
        for r in rows:
            # 解析 JSON 图片列表
            img_list = []
            if r[7]:
                try:
                    img_list = json.loads(r[7])
                except:
                    img_list = [r[7]] if r[7] else []
            
            logs.append({
                "id": r[0], "code": r[1], "old_qty": r[2], "new_qty": r[3],
                "ts": r[4], "project": r[5], "notes": r[6], "images": img_list,
                "type": r[8], "price": r[9]
            })
        return logs

    def update_log_meta(self, log_ids, project_name, notes, image_list):
        """image_list is a list of file paths"""
        json_str = json.dumps(image_list, ensure_ascii=False)
        with self._conn() as cx:
            for lid in log_ids:
                cx.execute("""UPDATE history 
                              SET project_name=?, notes=?, image_data=? 
                              WHERE id=?""", (project_name, notes, json_str, lid))

    def update(self, code, qty=None, threshold=None, notes=None):
        now = datetime.now().isoformat()
        with self._conn() as cx:
            if qty is not None:
                old = cx.execute("SELECT qty FROM beads WHERE code=?",(code,)).fetchone()
                cx.execute("UPDATE beads SET qty=?,updated=? WHERE code=?",(qty,now,code))
                cx.execute("INSERT INTO history(code,old_qty,new_qty,ts,project_name,notes,image_data,type,price) VALUES(?,?,?,?,'','', '[]','deduct',0)", 
                           (code, old[0] if old else 0, qty, now))
            if threshold is not None: cx.execute("UPDATE beads SET threshold=?,updated=? WHERE code=?",(threshold,now,code))
            if notes is not None: cx.execute("UPDATE beads SET notes=?,updated=? WHERE code=?",(notes,now,code))

    def record_change(self, code, old_qty, new_qty, proj_name, notes, img_list, log_type, price=0):
        now = datetime.now().isoformat()
        json_str = json.dumps(img_list, ensure_ascii=False)
        with self._conn() as cx:
            cx.execute("UPDATE beads SET qty=?,updated=? WHERE code=?",(new_qty,now,code))
            cx.execute("""INSERT INTO history(code, old_qty, new_qty, ts, project_name, notes, image_data, type, price) 
                          VALUES(?,?,?,?,?,?,?,?,?)""", 
                       (code, old_qty, new_qty, now, proj_name, notes, json_str, log_type, price))

    def bulk_deduct_with_log(self, data: dict, project_name: str, notes: str, image_list: list = []):
        with self._conn() as cx:
            for code, deduct_amt in data.items():
                old_row = cx.execute("SELECT qty FROM beads WHERE code=?",(code,)).fetchone()
                if not old_row: continue
                old_qty = old_row[0]
                new_qty = max(0, old_qty - deduct_amt)
                self.record_change(code, old_qty, new_qty, project_name, notes, image_list, "deduct")

    def bulk_restock_with_log(self, data: dict, source_name: str, notes: str, image_list: list = [], unit_price: float = 0.0):
        with self._conn() as cx:
            for code, add_amt in data.items():
                old_row = cx.execute("SELECT qty FROM beads WHERE code=?",(code,)).fetchone()
                if not old_row: continue
                old_qty = old_row[0]
                new_qty = old_qty + add_amt
                self.record_change(code, old_qty, new_qty, source_name, notes, image_list, "restock", unit_price)

    def export_csv(self, path):
        with open(path,"w",newline="",encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["code","hex","category","qty","threshold","notes"])
            w.writeheader(); w.writerows(self.get_all())

    def import_csv(self, path):
        data = {}
        with open(path,newline="",encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try: data[row["code"].strip()] = max(0, int(row["qty"]))
                except: pass
        now = datetime.now().isoformat()
        with self._conn() as cx:
            for code, qty in data.items():
                old = cx.execute("SELECT qty FROM beads WHERE code=?",(code,)).fetchone()
                if old:
                    cx.execute("INSERT INTO history(code,old_qty,new_qty,ts,project_name,notes,image_data,type,price) VALUES(?,?,?,?,'','[]','deduct',0)",
                               (code, old[0], qty, now))
                cx.execute("UPDATE beads SET qty=?,updated=? WHERE code=?",(qty,now,code))
        return len(data)

# ── 高性能色卡画布 (保持不变) ───────────────────────────────────────────────
class CardCanvas(tk.Canvas):
    def __init__(self, parent, on_select_cb, **kw):
        super().__init__(parent, **kw)
        self._cb, self._bboxes, self._selected, self._sorted, self._cols, self._resize_id = on_select_cb, [], None, [], 0, None
        self.bind("<Button-1>", self._click); self.bind("<Configure>", self._on_resize)
    def load(self, data: list, selected: str = None):
        self._sorted = sorted(data, key=sort_key); self._selected = selected; self._full_draw()
    def select(self, code: str):
        old, self._selected = self._selected, code
        for c in (old, code):
            if c:
                d = next((x for x in self._sorted if x["code"] == c), None)
                if d: self._repaint_one(c, d)
    def update_card(self, code: str, d: dict):
        global SORT_MODE
        if SORT_MODE == 'qty': self.load([x for x in self._sorted], self._selected)
        else:
            for i, x in enumerate(self._sorted):
                if x["code"] == code: self._sorted[i] = d; break
            self._repaint_one(code, d)
    def _on_resize(self, e):
        new_cols = max(1, (e.width - 16) // (CARD_W + CARD_GAP))
        if self._resize_id: self.after_cancel(self._resize_id)
        if new_cols != self._cols: self._resize_id = self.after(80, self._full_draw)
    def _full_draw(self):
        self.delete("all"); self._bboxes.clear()
        cw = self.winfo_width()
        if cw < 10: return
        step, cols, x0, y, col, cur_cat = CARD_W + CARD_GAP, max(1, (cw - 16) // (CARD_W + CARD_GAP)), 8, 8, 0, None
        self._cols = cols
        for d in self._sorted:
            if SORT_MODE == 'code' and d["cat"] != cur_cat:
                if col: y += CARD_H + CARD_GAP; col = 0
                cur_cat = d["cat"]
                self.create_text(x0+4, y+11, text=f"  {CAT_NAMES.get(cur_cat, cur_cat)}", font=("SimHei",10,"bold"), fill="#dfe6e9", anchor="w")
                y += 26
            cx = x0 + col*step
            self._paint(cx, y, d)
            self._bboxes.append((cx, y, cx+CARD_W, y+CARD_H, d["code"]))
            col += 1
            if col >= cols: col = 0; y += CARD_H + CARD_GAP
        self.configure(scrollregion=(0, 0, cw, y + CARD_H + 20))
    def _paint(self, x, y, d):
        code, hx, qty, thr = d["code"], d["hex"], d["qty"], d["threshold"]
        fg = fg_for(hx)
        is_zero, is_low, is_sel = qty == 0, (0 < qty <= thr), code == self._selected
        border = "#74b9ff" if is_sel else "#e74c3c" if is_zero else "#f39c12" if is_low else hx
        bw = 3 if is_sel else (2 if (is_zero or is_low) else 1)
        tag = f"c_{code}"
        self.create_rectangle(x, y, x+CARD_W, y+CARD_H, fill=hx, outline=border, width=bw, tags=tag)
        self.create_text(x+CARD_W//2, y+CARD_H//2-8, text=code, fill=fg, font=("Arial",8,"bold"), tags=tag)
        qty_t = "缺货" if is_zero else (f"⚠{qty}" if is_low else str(qty))
        qty_c = "#ff6b6b" if is_zero else ("#ffd32a" if is_low else fg)
        self.create_text(x+CARD_W//2, y+CARD_H-14, text=qty_t, fill=qty_c, font=("Arial",8), tags=tag)
    def _repaint_one(self, code: str, d: dict):
        for x1, y1, *_, c in self._bboxes:
            if c == code: self.delete(f"c_{code}"); self._paint(x1, y1, d); return
    def _click(self, e):
        cx, cy = self.canvasx(e.x), self.canvasy(e.y)
        for x1, y1, x2, y2, code in self._bboxes:
            if x1 <= cx <= x2 and y1 <= cy <= y2: self._cb(code); return

# ── 多图选择与管理组件 (新功能) ─────────────────────────────────────────────
class MultiImagePicker(tk.Frame):
    def __init__(self, parent, initial_images=None, on_change=None):
        super().__init__(parent, bg="#f5f6fa")
        self.image_list = initial_images if initial_images else []
        self.on_change = on_change
        self.photo_refs = [] # 防止垃圾回收
        
        self._build_ui()
        self._refresh_display()

    def _build_ui(self):
        # 顶部操作栏
        top = tk.Frame(self, bg="#f5f6fa")
        top.pack(fill="x", pady=(0, 5))
        
        tk.Button(top, text="📷 添加图片", command=self._add_images, bg="#0984e3", fg="white", relief="flat", font=("SimHei", 9)).pack(side="left")
        tk.Label(top, text="支持多选，最多9张", font=("SimHei", 8), bg="#f5f6fa", fg="#b2bec3").pack(side="left", padx=10)
        
        # 图片展示区 (横向滚动)
        self.canvas_frame = tk.Frame(self, bg="#dfe6e9", height=110)
        self.canvas_frame.pack(fill="x", pady=5)
        self.canvas_frame.pack_propagate(False)
        
        self.scroll_canvas = tk.Canvas(self.canvas_frame, bg="#dfe6e9", highlightthickness=0, height=110)
        scrollbar = ttk.Scrollbar(self.canvas_frame, orient="horizontal", command=self.scroll_canvas.xview)
        self.scrollable_frame = tk.Frame(self.scroll_canvas, bg="#dfe6e9")
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))
        )
        
        self.scroll_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.scroll_canvas.configure(xscrollcommand=scrollbar.set)
        
        self.scroll_canvas.pack(side="top", fill="x", expand=True)
        scrollbar.pack(side="bottom", fill="x")
        
        # 绑定鼠标滚轮横向滚动
        self.scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.scroll_canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.scroll_canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        if event.num == 5 or event.delta == -120:
            dir = 1
        else:
            dir = -1
        self.scroll_canvas.xview_scroll(dir, "units")

    def _add_images(self):
        if not HAS_PIL:
            messagebox.showwarning("提示", "未安装 Pillow 库。")
            return
        paths = filedialog.askopenfilenames(title="选择多张图片", filetypes=[("图片", "*.jpg *.png *.jpeg *.bmp"), ("所有", "*.*")])
        if not paths: return
        
        new_imgs = []
        for path in paths:
            if len(self.image_list) + len(new_imgs) >= 9:
                messagebox.showwarning("限制", "最多只能上传 9 张图片。")
                break
            ext = os.path.splitext(path)[1]
            new_filename = f"img_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
            dest = os.path.join(IMG_FOLDER, new_filename)
            try:
                shutil.copy2(path, dest)
                new_imgs.append(dest)
            except Exception as e:
                messagebox.showerror("错误", f"复制图片失败：{e}")
        
        if new_imgs:
            self.image_list.extend(new_imgs)
            self._refresh_display()
            if self.on_change: self.on_change(self.image_list)

    def _refresh_display(self):
        # 清空现有缩略图
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.photo_refs = []
        
        if not self.image_list:
            tk.Label(self.scrollable_frame, text="暂无图片", bg="#dfe6e9", fg="#636e72", font=("SimHei", 9)).pack(pady=35)
            return
            
        for idx, img_path in enumerate(self.image_list):
            frame = tk.Frame(self.scrollable_frame, bg="#dfe6e9", padx=5, pady=5)
            frame.pack(side="left")
            
            if HAS_PIL and os.path.exists(img_path):
                try:
                    img = Image.open(img_path)
                    # 生成缩略图 80x80
                    img.thumbnail((80, 80), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    self.photo_refs.append(photo)
                    
                    lbl = tk.Label(frame, image=photo, bg="#fff", cursor="hand2")
                    lbl.pack()
                    lbl.bind("<Button-1>", lambda e, p=img_path: self._preview_image(p))
                    
                    # 删除按钮
                    btn_del = tk.Button(frame, text="×", bg="#ff7675", fg="white", font=("Arial", 8, "bold"), 
                                        command=lambda i=img_path: self._remove_image(i), padx=2, pady=0)
                    btn_del.pack(fill="x")
                except:
                    tk.Label(frame, text="加载失败", bg="#fff", font=("SimHei", 8)).pack()
            else:
                tk.Label(frame, text="文件丢失", bg="#fff", font=("SimHei", 8)).pack()

    def _remove_image(self, path_to_remove):
        if messagebox.askyesno("确认", "确定删除这张图片吗？"):
            # 物理删除文件
            if os.path.exists(path_to_remove):
                try: os.remove(path_to_remove)
                except: pass
            self.image_list.remove(path_to_remove)
            self._refresh_display()
            if self.on_change: self.on_change(self.image_list)

    def _preview_image(self, path):
        if not HAS_PIL or not os.path.exists(path): return
        win = tk.Toplevel(self)
        win.title("图片预览")
        win.configure(bg="#2d3436")
        
        img = Image.open(path)
        # 限制最大显示尺寸
        max_w, max_h = 800, 600
        ratio = min(max_w/img.width, max_h/img.height)
        new_size = (int(img.width*ratio), int(img.height*ratio))
        img = img.resize(new_size, Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        
        lbl = tk.Label(win, image=photo, bg="#2d3436")
        lbl.image = photo # keep reference
        lbl.pack(padx=20, pady=20)
        
        tk.Button(win, text="关闭", command=win.destroy, bg="#636e72", fg="white").pack(pady=10)

    def get_images(self):
        return self.image_list

# ── 极速扣除对话框 (升级为多图) ─────────────────────────────────────────────
class FastDeductDialog(tk.Toplevel):
    def __init__(self, parent, db: BeadDB, all_data: list, on_done):
        super().__init__(parent)
        self.title("⚡ 极速扣除 & 记录")
        self.geometry("850x650")
        self.minsize(650, 500)
        self.configure(bg="#2d3436")
        
        self._db = db
        self._db_map = {d["code"]: d for d in all_data}
        self._plan = {}
        self._on_done = on_done
        self._current_images = []
        
        self._build_ui()
        self._input.focus_set()

    def _build_ui(self):
        top_frame = tk.Frame(self, bg="#2d3436")
        top_frame.pack(fill="x", padx=20, pady=10)
        tk.Label(top_frame, text="📦 作品:", font=("SimHei", 10), bg="#2d3436", fg="#fff").pack(side="left", padx=(0,5))
        self._proj_entry = tk.Entry(top_frame, font=("SimHei", 11), bg="#dfe6e9", fg="#2d3436", relief="flat", width=20)
        self._proj_entry.pack(side="left", padx=5)
        self._proj_entry.insert(0, datetime.now().strftime("%Y-%m-%d 作品"))
        
        tk.Label(top_frame, text="📝 备注:", font=("SimHei", 10), bg="#2d3436", fg="#fff").pack(side="left", padx=(15,5))
        self._note_entry = tk.Entry(top_frame, font=("SimHei", 11), bg="#dfe6e9", fg="#2d3436", relief="flat", width=30)
        self._note_entry.pack(side="left", padx=5)
        
        # 替换为多图选择器
        self._img_picker = MultiImagePicker(top_frame, on_change=lambda lst: setattr(self, '_current_images', lst))
        self._img_picker.pack(side="right", padx=5)

        inp_frame = tk.Frame(self, bg="#2d3436")
        inp_frame.pack(fill="x", padx=20, pady=5)
        tk.Label(inp_frame, text=">", font=("Consolas", 14), fg="#00cec9", bg="#2d3436").pack(side="left", padx=(0, 5))
        self._input = tk.Entry(inp_frame, font=("Consolas", 14), bg="#dfe6e9", fg="#2d3436", relief="flat", highlightthickness=2, highlightbackground="#636e72", highlightcolor="#00cec9")
        self._input.pack(side="left", fill="x", expand=True, ipady=5)
        self._input.bind("<Return>", self._on_enter)
        self._input.bind("<Escape>", lambda e: self.destroy())
        self._msg_lbl = tk.Label(inp_frame, text="就绪 (例: A1:10)", font=("SimHei", 9), bg="#2d3436", fg="#fab1a0")
        self._msg_lbl.pack(side="right", padx=10)

        list_frame = tk.Frame(self, bg="#2d3436")
        list_frame.pack(fill="both", expand=True, padx=20, pady=10)
        cols = ("code", "stock", "deduct", "after", "status")
        self._tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=12)
        self._tree.heading("code", text="色号"); self._tree.column("code", width=80, anchor="center")
        self._tree.heading("stock", text="库存"); self._tree.column("stock", width=70, anchor="center")
        self._tree.heading("deduct", text="扣除"); self._tree.column("deduct", width=70, anchor="center")
        self._tree.heading("after", text="剩余"); self._tree.column("after", width=70, anchor="center")
        self._tree.heading("status", text="状态"); self._tree.column("status", width=100, anchor="center")
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.tag_configure("ok", foreground="#2d3436")
        self._tree.tag_configure("warn", foreground="#e17055", background="#ffeaa7")
        self._tree.tag_configure("over", foreground="#d63031", background="#ff7675")
        self._tree.bind("<Delete>", self._remove_selected)
        self._tree.bind("<BackSpace>", self._remove_selected)
        self._tree.bind("<KeyRelease>", self._on_list_key)
        self._tree.bind("<Double-1>", lambda e: self._edit_selected_amt())

        bot = tk.Frame(self, bg="#2d3436")
        bot.pack(fill="x", padx=20, pady=(0, 15))
        self._sum_lbl = tk.Label(bot, text="合计: 0 颗", font=("Consolas", 12, "bold"), bg="#2d3436", fg="#fff")
        self._sum_lbl.pack(side="left")
        btn_frame = tk.Frame(bot, bg="#2d3436")
        btn_frame.pack(side="right")
        tk.Button(btn_frame, text="取消", command=self.destroy, bg="#636e72", fg="white", relief="flat", font=("SimHei", 10), padx=15, cursor="hand2").pack(side="right", padx=5)
        tk.Button(btn_frame, text="✅ 确认扣除", command=self._confirm, bg="#00b894", fg="white", relief="flat", font=("SimHei", 10, "bold"), padx=15, cursor="hand2").pack(side="right", padx=5)
        self.bind("<Control-Return>", lambda e: self._confirm())

    # ... (省略中间逻辑，保持与之前一致，只改_confirm中的图片获取) ...
    # 为了节省篇幅，这里复用之前的逻辑，只需修改_parse_input, _on_enter等无关图片的部分保持不变
    # 重点修改 _confirm 方法
    
    def _parse_input(self, text):
        items = []
        pattern = r"([A-Za-z]+\d+)\s*[:,\s]\s*(\d+)"
        matches = re.findall(pattern, text)
        if not matches: return []
        for code, amt_str in matches:
            code = code.upper()
            amt = int(amt_str)
            if code in self._db_map:
                items.append((code, amt))
            else:
                self._msg_lbl.configure(text=f"❌ 未知: {code}", fg="#ff7675")
                self.after(2000, lambda: self._msg_lbl.configure(text="就绪", fg="#fab1a0"))
        return items

    def _on_enter(self, event):
        text = self._input.get().strip()
        if not text: return
        items = self._parse_input(text)
        if not items:
            self._msg_lbl.configure(text="⚠️ 格式错误", fg="#fdcb6e")
            self.after(2000, lambda: self._msg_lbl.configure(text="就绪", fg="#fab1a0"))
            return
        for code, amt in items:
            if code in self._plan:
                self._plan[code]["amt"] += amt
            else:
                self._plan[code] = {"d": self._db_map[code], "amt": amt}
        self._input.delete(0, "end")
        self._refresh_tree()
        if items:
            last_code = items[-1][0]
            self._tree.selection_set(last_code)
            self._tree.see(last_code)
            self._tree.focus_set()
            self._tree.focus(last_code)

    def _refresh_tree(self):
        self._tree.delete(*self._tree.get_children())
        total_amt = 0
        has_error = False
        for code, item in self._plan.items():
            amt = item["amt"]
            stock = item["d"]["qty"]
            after = max(0, stock - amt)
            total_amt += amt
            status = "正常"
            tag = "ok"
            if amt > stock:
                status = "超库存"
                tag = "over"
                has_error = True
            elif after <= item["d"]["threshold"]:
                status = "将低库存"
                tag = "warn"
            self._tree.insert("", "end", iid=code, values=(code, stock, amt, after, status), tags=(tag,))
        self._sum_lbl.configure(text=f"合计: {total_amt} 颗 | {len(self._plan)} 种", fg="#ff7675" if has_error else "#00b894")

    def _on_list_key(self, event):
        sel = self._tree.selection()
        if not sel: return
        code = sel[0]
        if event.keysym in ("plus", "Add"): self._change_amt(code, 1)
        elif event.keysym in ("minus", "Subtract"): self._change_amt(code, -1)
        elif event.keysym in ("Return", "KP_Enter"): self._edit_selected_amt()

    def _change_amt(self, code, delta):
        if code not in self._plan: return
        self._plan[code]["amt"] = max(0, self._plan[code]["amt"] + delta)
        self._refresh_tree()
        self._tree.selection_set(code)

    def _edit_selected_amt(self):
        sel = self._tree.selection()
        if not sel: return
        code = sel[0]
        val = simpledialog.askinteger("修改", f"{code} 新数量?", initialvalue=self._plan[code]["amt"], minvalue=0, parent=self)
        if val is not None:
            self._plan[code]["amt"] = val
            self._refresh_tree()

    def _remove_selected(self, event=None):
        for code in self._tree.selection():
            self._plan.pop(code, None)
        self._refresh_tree()
        if not self._plan: self._input.focus_set()

    def _confirm(self):
        if not self._plan:
            messagebox.showinfo("提示", "清单为空")
            return
        proj_name = self._proj_entry.get().strip() or "未命名作品"
        notes = self._note_entry.get().strip()
        images = self._img_picker.get_images()
        
        over = [c for c, it in self._plan.items() if it["amt"] > it["d"]["qty"]]
        if over and not messagebox.askyesno("警告", f"以下颜色超库存:\n{', '.join(over)}\n继续?", parent=self):
            return
        preview = "\n".join(f"  {c}: {it['d']['qty']}→{max(0, it['d']['qty']-it['amt'])}" for c, it in list(self._plan.items())[:8])
        if len(self._plan) > 8: preview += "\n..."
        msg = f"作品：{proj_name}\n扣除:\n{preview}"
        if images: msg += f"\n📷 附带 {len(images)} 张图片"
        if notes: msg += f"\n📝 {notes}"
        if messagebox.askyesno("确认记录", msg, parent=self):
            updates = {c: it["amt"] for c, it in self._plan.items()}
            self._db.bulk_deduct_with_log(updates, proj_name, notes, images)
            self._on_done()
            self.destroy()
            messagebox.showinfo("完成", f"✅ 已记录作品 '{proj_name}' 并更新库存")

# ── 极速补货对话框 (升级为多图) ─────────────────────────────────────────────
class FastRestockDialog(tk.Toplevel):
    def __init__(self, parent, db: BeadDB, all_data: list, on_done):
        super().__init__(parent)
        self.title("🛒 极速补货 & 记录")
        self.geometry("850x650")
        self.minsize(650, 500)
        self.configure(bg="#2d3436")
        
        self._db = db
        self._db_map = {d["code"]: d for d in all_data}
        self._plan = {}
        self._on_done = on_done
        self._current_images = []
        
        self._build_ui()
        self._input.focus_set()

    def _build_ui(self):
        top_frame = tk.Frame(self, bg="#2d3436")
        top_frame.pack(fill="x", padx=20, pady=10)
        
        tk.Label(top_frame, text="🏪 来源/批次:", font=("SimHei", 10), bg="#2d3436", fg="#fff").pack(side="left", padx=(0,5))
        self._proj_entry = tk.Entry(top_frame, font=("SimHei", 11), bg="#dfe6e9", fg="#2d3436", relief="flat", width=20)
        self._proj_entry.pack(side="left", padx=5)
        self._proj_entry.insert(0, datetime.now().strftime("%Y-%m-%d 采购"))
        
        tk.Label(top_frame, text="💰 单价(元):", font=("SimHei", 10), bg="#2d3436", fg="#fff").pack(side="left", padx=(15,5))
        self._price_entry = tk.Entry(top_frame, font=("SimHei", 11), bg="#dfe6e9", fg="#2d3436", relief="flat", width=8)
        self._price_entry.pack(side="left", padx=5)
        self._price_entry.insert(0, "0.05")
        
        tk.Label(top_frame, text="📝 备注:", font=("SimHei", 10), bg="#2d3436", fg="#fff").pack(side="left", padx=(10,5))
        self._note_entry = tk.Entry(top_frame, font=("SimHei", 11), bg="#dfe6e9", fg="#2d3436", relief="flat", width=20)
        self._note_entry.pack(side="left", padx=5)
        
        # 替换为多图选择器
        self._img_picker = MultiImagePicker(top_frame, on_change=lambda lst: setattr(self, '_current_images', lst))
        self._img_picker.pack(side="right", padx=5)

        inp_frame = tk.Frame(self, bg="#2d3436")
        inp_frame.pack(fill="x", padx=20, pady=5)
        tk.Label(inp_frame, text="+", font=("Consolas", 14), fg="#00b894", bg="#2d3436").pack(side="left", padx=(0, 5))
        self._input = tk.Entry(inp_frame, font=("Consolas", 14), bg="#dfe6e9", fg="#2d3436", relief="flat", highlightthickness=2, highlightbackground="#636e72", highlightcolor="#00b894")
        self._input.pack(side="left", fill="x", expand=True, ipady=5)
        self._input.bind("<Return>", self._on_enter)
        self._input.bind("<Escape>", lambda e: self.destroy())
        self._msg_lbl = tk.Label(inp_frame, text="就绪 (例: A1:100)", font=("SimHei", 9), bg="#2d3436", fg="#fab1a0")
        self._msg_lbl.pack(side="right", padx=10)

        list_frame = tk.Frame(self, bg="#2d3436")
        list_frame.pack(fill="both", expand=True, padx=20, pady=10)
        cols = ("code", "stock", "add", "after", "status")
        self._tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=12)
        self._tree.heading("code", text="色号"); self._tree.column("code", width=80, anchor="center")
        self._tree.heading("stock", text="原库存"); self._tree.column("stock", width=70, anchor="center")
        self._tree.heading("add", text="入库"); self._tree.column("add", width=70, anchor="center")
        self._tree.heading("after", text="新库存"); self._tree.column("after", width=70, anchor="center")
        self._tree.heading("status", text="状态"); self._tree.column("status", width=100, anchor="center")
        
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        
        self._tree.tag_configure("ok", foreground="#2d3436")
        self._tree.tag_configure("new", foreground="#00b894", background="#dff9fb")
        
        self._tree.bind("<Delete>", self._remove_selected)
        self._tree.bind("<BackSpace>", self._remove_selected)
        self._tree.bind("<KeyRelease>", self._on_list_key)
        self._tree.bind("<Double-1>", lambda e: self._edit_selected_amt())

        bot = tk.Frame(self, bg="#2d3436")
        bot.pack(fill="x", padx=20, pady=(0, 15))
        self._sum_lbl = tk.Label(bot, text="合计: 0 颗", font=("Consolas", 12, "bold"), bg="#2d3436", fg="#fff")
        self._sum_lbl.pack(side="left")
        btn_frame = tk.Frame(bot, bg="#2d3436")
        btn_frame.pack(side="right")
        tk.Button(btn_frame, text="取消", command=self.destroy, bg="#636e72", fg="white", relief="flat", font=("SimHei", 10), padx=15, cursor="hand2").pack(side="right", padx=5)
        tk.Button(btn_frame, text="✅ 确认入库", command=self._confirm, bg="#00b894", fg="white", relief="flat", font=("SimHei", 10, "bold"), padx=15, cursor="hand2").pack(side="right", padx=5)
        self.bind("<Control-Return>", lambda e: self._confirm())

    # ... (复用之前的逻辑，仅修改_confirm) ...
    def _parse_input(self, text):
        items = []
        pattern = r"([A-Za-z]+\d+)\s*[:,\s]\s*(\d+)"
        matches = re.findall(pattern, text)
        if not matches: return []
        for code, amt_str in matches:
            code = code.upper()
            amt = int(amt_str)
            if code in self._db_map:
                items.append((code, amt))
            else:
                self._msg_lbl.configure(text=f"❌ 未知: {code}", fg="#ff7675")
                self.after(2000, lambda: self._msg_lbl.configure(text="就绪", fg="#fab1a0"))
        return items

    def _on_enter(self, event):
        text = self._input.get().strip()
        if not text: return
        items = self._parse_input(text)
        if not items:
            self._msg_lbl.configure(text="⚠️ 格式错误", fg="#fdcb6e")
            self.after(2000, lambda: self._msg_lbl.configure(text="就绪", fg="#fab1a0"))
            return
        for code, amt in items:
            if code in self._plan:
                self._plan[code]["amt"] += amt
            else:
                self._plan[code] = {"d": self._db_map[code], "amt": amt}
        self._input.delete(0, "end")
        self._refresh_tree()
        if items:
            last_code = items[-1][0]
            self._tree.selection_set(last_code)
            self._tree.see(last_code)
            self._tree.focus_set()
            self._tree.focus(last_code)

    def _refresh_tree(self):
        self._tree.delete(*self._tree.get_children())
        total_amt = 0
        for code, item in self._plan.items():
            amt = item["amt"]
            stock = item["d"]["qty"]
            after = stock + amt
            total_amt += amt
            status = "正常"
            tag = "ok"
            if stock == 0:
                status = "补货复活"
                tag = "new"
            self._tree.insert("", "end", iid=code, values=(code, stock, amt, after, status), tags=(tag,))
        self._sum_lbl.configure(text=f"合计入库: {total_amt} 颗 | {len(self._plan)} 种", fg="#00b894")

    def _on_list_key(self, event):
        sel = self._tree.selection()
        if not sel: return
        code = sel[0]
        if event.keysym in ("plus", "Add"): self._change_amt(code, 1)
        elif event.keysym in ("minus", "Subtract"): self._change_amt(code, -1)
        elif event.keysym in ("Return", "KP_Enter"): self._edit_selected_amt()

    def _change_amt(self, code, delta):
        if code not in self._plan: return
        self._plan[code]["amt"] = max(0, self._plan[code]["amt"] + delta)
        self._refresh_tree()
        self._tree.selection_set(code)

    def _edit_selected_amt(self):
        sel = self._tree.selection()
        if not sel: return
        code = sel[0]
        val = simpledialog.askinteger("修改", f"{code} 入库数量?", initialvalue=self._plan[code]["amt"], minvalue=1, parent=self)
        if val is not None:
            self._plan[code]["amt"] = val
            self._refresh_tree()

    def _remove_selected(self, event=None):
        for code in self._tree.selection():
            self._plan.pop(code, None)
        self._refresh_tree()
        if not self._plan: self._input.focus_set()

    def _confirm(self):
        if not self._plan:
            messagebox.showinfo("提示", "清单为空")
            return
        source = self._proj_entry.get().strip() or "未记录来源"
        notes = self._note_entry.get().strip()
        try:
            price = float(self._price_entry.get().strip() or 0)
        except:
            price = 0.0
        images = self._img_picker.get_images()
            
        preview = "\n".join(f"  {c}: {it['d']['qty']}→{it['d']['qty']+it['amt']}" for c, it in list(self._plan.items())[:8])
        if len(self._plan) > 8: preview += "\n..."
        msg = f"来源：{source}\n单价：¥{price}\n入库:\n{preview}"
        if images: msg += f"\n📷 附带 {len(images)} 张凭证"
        if notes: msg += f"\n📝 {notes}"
        
        if messagebox.askyesno("确认入库", msg, parent=self):
            updates = {c: it["amt"] for c, it in self._plan.items()}
            self._db.bulk_restock_with_log(updates, source, notes, images, price)
            self._on_done()
            self.destroy()
            messagebox.showinfo("完成", f"✅ 已记录补货 '{source}' 并更新库存")

# ── 编辑日志对话框 (升级为多图编辑) ─────────────────────────────────────────
class EditLogDialog(tk.Toplevel):
    def __init__(self, parent, db: BeadDB, group_data, on_refresh):
        super().__init__(parent)
        self.title("✏️ 编辑日志")
        self.geometry("500x600") # 增加高度以适应多图组件
        self.resizable(False, True) # 允许垂直调整
        self.configure(bg="#f5f6fa")
        
        self._db = db
        self._group = group_data
        self._on_refresh = on_refresh
        
        log_type = group_data.get("type", "deduct")
        type_text = "补货" if log_type == "restock" else "作品"
        self.title(f"✏️ 编辑{type_text}日志")
        
        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self, bg="#f5f6fa")
        main.pack(fill="both", expand=True, padx=20, pady=15)
        
        tk.Label(main, text="⚠️ 注意：时间和数量不可修改。", 
                 font=("SimHei", 9), bg="#f5f6fa", fg="#e17055").pack(anchor="w", pady=(0, 5))
        
        label_text = "🏪 来源" if self._group.get("type") == "restock" else "📦 作品名称"
        tk.Label(main, text=label_text, font=("SimHei", 10, "bold"), bg="#f5f6fa").pack(anchor="w")
        self._entry_proj = tk.Entry(main, font=("SimHei", 11), bg="#fff", relief="groove", bd=1)
        self._entry_proj.pack(fill="x", pady=(0, 10))
        self._entry_proj.insert(0, self._group["proj"])
        
        tk.Label(main, text="📝 备注详情", font=("SimHei", 10, "bold"), bg="#f5f6fa").pack(anchor="w")
        self._text_notes = tk.Text(main, font=("SimHei", 10), bg="#fff", relief="groove", bd=1, height=4)
        self._text_notes.pack(fill="both", expand=True, pady=(0, 10))
        if self._group["notes"]:
            self._text_notes.insert("1.0", self._group["notes"])
            
        tk.Label(main, text="🖼️ 图片管理 (可增删)", font=("SimHei", 10, "bold"), bg="#f5f6fa").pack(anchor="w")
        # 使用新的多图选择器
        self._img_picker = MultiImagePicker(main, initial_images=self._group["images"])
        self._img_picker.pack(fill="x", pady=(0, 10))
        
        sep = ttk.Separator(main, orient="horizontal")
        sep.pack(fill="x", pady=10)
        
        bot = tk.Frame(main, bg="#f5f6fa")
        bot.pack(fill="x", side="bottom")
        tk.Button(bot, text="取消", command=self.destroy, bg="#b2bec3", fg="white", relief="flat", font=("SimHei", 10), padx=20).pack(side="right", padx=5)
        tk.Button(bot, text="💾 保存修改", command=self._save, bg="#00b894", fg="white", relief="flat", font=("SimHei", 10, "bold"), padx=20).pack(side="right", padx=5)

    def _save(self):
        proj = self._entry_proj.get().strip()
        notes = self._text_notes.get("1.0", "end").strip()
        images = self._img_picker.get_images()
        
        if not proj:
            messagebox.showwarning("提示", "名称不能为空")
            return
        self._db.update_log_meta(self._group["ids"], proj, notes, images)
        self._on_refresh()
        self.destroy()
        messagebox.showinfo("成功", "日志信息已更新")

# ── 作品日志查看器 (升级为多图展示) ───────────────────────────────────────
class ProjectLogViewer(tk.Toplevel):
    def __init__(self, parent, db: BeadDB):
        super().__init__(parent)
        self.title("📚 进出库日志 (双击可编辑)")
        self.geometry("900x700")
        self.configure(bg="#f5f6fa")
        self._db = db
        self._logs = []
        self._current_img_refs = []
        self._grouped_data = {}
        
        self._build_ui()
        self._load_logs()

    def _build_ui(self):
        paned = tk.PanedWindow(self, orient="horizontal", bg="#b2bec3", sashwidth=5)
        paned.pack(fill="both", expand=True, padx=10, pady=10)
        
        left = tk.Frame(paned, bg="#fff")
        paned.add(left, minsize=300)
        
        tk.Label(left, text="历史记录 (双击编辑)", font=("SimHei", 12, "bold"), bg="#fff", fg="#2d3436").pack(pady=10)
        
        cols = ("time", "type", "proj", "codes", "total")
        self._tree = ttk.Treeview(left, columns=cols, show="headings", height=20)
        self._tree.heading("time", text="时间"); self._tree.column("time", width=130)
        self._tree.heading("type", text="类型"); self._tree.column("type", width=60, anchor="center")
        self._tree.heading("proj", text="来源/作品"); self._tree.column("proj", width=120)
        self._tree.heading("codes", text="涉及色号"); self._tree.column("codes", width=100)
        self._tree.heading("total", text="数量"); self._tree.column("total", width=60, anchor="center")
        
        sb = ttk.Scrollbar(left, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        
        self._tree.tag_configure("restock", foreground="#00b894", background="#e3fcf7")
        self._tree.tag_configure("deduct", foreground="#d63031", background="#ffeaea")
        
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-1>", self._on_double_click)
        
        right = tk.Frame(paned, bg="#f5f6fa")
        paned.add(right, minsize=400)
        
        info_frame = tk.Frame(right, bg="#f5f6fa")
        info_frame.pack(fill="x", padx=20, pady=10)
        self._lbl_title = tk.Label(info_frame, text="选择记录查看详情", font=("SimHei", 14, "bold"), bg="#f5f6fa", fg="#636e72")
        self._lbl_title.pack(anchor="w")
        self._lbl_time = tk.Label(info_frame, text="", font=("Consolas", 10), bg="#f5f6fa", fg="#b2bec3")
        self._lbl_time.pack(anchor="w")
        self._lbl_price = tk.Label(info_frame, text="", font=("SimHei", 10, "bold"), bg="#f5f6fa", fg="#00b894")
        self._lbl_price.pack(anchor="w")
        
        sep = ttk.Separator(right, orient="horizontal")
        sep.pack(fill="x", padx=20, pady=10)
        
        # 图片区域改为 Frame 容器，用于放置多张缩略图
        self._img_container = tk.Frame(right, bg="#f5f6fa", height=150)
        self._img_container.pack(fill="x", padx=20, pady=10)
        self._img_container.pack_propagate(False)
        
        tk.Label(right, text="备注:", font=("SimHei", 10, "bold"), bg="#f5f6fa", fg="#2d3436").pack(anchor="w", padx=20, pady=(10,0))
        self._txt_notes = tk.Text(right, height=6, font=("SimHei", 10), bg="#fff", fg="#2d3436", relief="flat", wrap="word")
        self._txt_notes.pack(fill="x", padx=20, pady=5)
        self._txt_notes.configure(state="disabled")
        
        tk.Label(right, text="明细:", font=("SimHei", 10, "bold"), bg="#f5f6fa", fg="#2d3436").pack(anchor="w", padx=20, pady=(10,0))
        detail_frame = tk.Frame(right, bg="#fff")
        detail_frame.pack(fill="both", expand=True, padx=20, pady=5)
        
        self._detail_tree = ttk.Treeview(detail_frame, columns=("c", "old", "new", "diff"), show="headings", height=8)
        self._detail_tree.heading("c", text="色号"); self._detail_tree.column("c", width=60, anchor="center")
        self._detail_tree.heading("old", text="原"); self._detail_tree.column("old", width=50, anchor="center")
        self._detail_tree.heading("new", text="新"); self._detail_tree.column("new", width=50, anchor="center")
        self._detail_tree.heading("diff", text="变动"); self._detail_tree.column("diff", width=60, anchor="center")
        self._detail_tree.pack(fill="both", expand=True)
        
        tk.Button(right, text="关闭", command=self.destroy, bg="#636e72", fg="white", relief="flat", font=("SimHei", 10), padx=20).pack(pady=10)

    def _load_logs(self):
        self._logs = self._db.get_history_logs(limit=200)
        self._tree.delete(*self._tree.get_children())
        self._grouped_data = {}
        
        groups = {}
        for log in self._logs:
            key = (log["project"], log["ts"][:16], log["type"])
            if key not in groups:
                groups[key] = {"ids": [], "logs": [], "total": 0, "codes": set(), "ts": log["ts"], "proj": log["project"], "notes": log["notes"], "images": log["images"], "type": log["type"], "price": log["price"]}
            groups[key]["ids"].append(log["id"])
            groups[key]["logs"].append(log)
            change = log["new_qty"] - log["old_qty"]
            groups[key]["total"] += change
            groups[key]["codes"].add(log["code"])
            
        sorted_keys = sorted(groups.keys(), key=lambda k: groups[k]["ts"], reverse=True)
        
        for i, key in enumerate(sorted_keys):
            data = groups[key]
            iid = f"g_{i}"
            codes_str = ", ".join(sorted(data["codes"]))
            if len(codes_str) > 12: codes_str = codes_str[:9] + "..."
            
            type_tag = data["type"]
            type_display = "🛒 入库" if data["type"] == "restock" else "⚡ 出库"
            total_display = f"+{data['total']}" if data["type"] == "restock" else f"-{abs(data['total'])}"
            
            self._tree.insert("", "end", iid=iid, values=(
                data["ts"].replace("T", " ")[5:],
                type_display,
                data["proj"],
                codes_str,
                total_display
            ), tags=(type_tag,))
            self._grouped_data[iid] = data

    def _on_select(self, event):
        sel = self._tree.selection()
        if not sel: return
        self._show_details(sel[0])

    def _on_double_click(self, event):
        sel = self._tree.selection()
        if not sel: return
        iid = sel[0]
        data = self._grouped_data.get(iid)
        if data:
            EditLogDialog(self, self._db, data, self._load_logs)

    def _show_details(self, iid):
        data = self._grouped_data.get(iid)
        if not data: return
        
        type_text = "补货来源" if data["type"] == "restock" else "作品名称"
        self._lbl_title.configure(text=f"{type_text}: {data['proj']}", fg="#2d3436")
        self._lbl_time.configure(text=data["ts"].replace("T", " "))
        
        if data["type"] == "restock" and data["price"] > 0:
            self._lbl_price.configure(text=f"💰 单价: ¥{data['price']}")
        else:
            self._lbl_price.configure(text="")
        
        self._txt_notes.configure(state="normal")
        self._txt_notes.delete("1.0", "end")
        self._txt_notes.insert("1.0", data["notes"] if data["notes"] else "无备注")
        self._txt_notes.configure(state="disabled")
        
        # 清除旧图片
        for widget in self._img_container.winfo_children():
            widget.destroy()
        self._current_img_refs = []
        
        # 显示多张缩略图
        if data["images"]:
            for img_path in data["images"]:
                if HAS_PIL and os.path.exists(img_path):
                    try:
                        img = Image.open(img_path)
                        img.thumbnail((100, 100), Image.LANCZOS)
                        photo = ImageTk.PhotoImage(img)
                        self._current_img_refs.append(photo)
                        
                        frame = tk.Frame(self._img_container, bg="#fff", padx=2, pady=2, relief="raised", bd=1)
                        frame.pack(side="left", padx=5)
                        lbl = tk.Label(frame, image=photo, bg="#fff", cursor="hand2")
                        lbl.pack()
                        lbl.bind("<Button-1>", lambda e, p=img_path: self._preview_image(p))
                    except:
                        pass
                else:
                    tk.Label(self._img_container, text="图片缺失", bg="#ffeaa7").pack(side="left", padx=5)
        else:
            tk.Label(self._img_container, text="无图片", bg="#f5f6fa", fg="#b2bec3").pack()
        
        self._detail_tree.delete(*self._detail_tree.get_children())
        for log in data["logs"]:
            diff = log["new_qty"] - log["old_qty"]
            sign = "+" if diff > 0 else ""
            color_tag = "in" if diff > 0 else "out"
            self._detail_tree.insert("", "end", values=(log["code"], log["old_qty"], log["new_qty"], f"{sign}{diff}"), tags=(color_tag,))
        self._detail_tree.tag_configure("in", foreground="#00b894")
        self._detail_tree.tag_configure("out", foreground="#d63031")

    def _preview_image(self, path):
        if not HAS_PIL or not os.path.exists(path): return
        win = tk.Toplevel(self)
        win.title("图片预览")
        win.configure(bg="#2d3436")
        
        img = Image.open(path)
        max_w, max_h = 800, 600
        ratio = min(max_w/img.width, max_h/img.height)
        new_size = (int(img.width*ratio), int(img.height*ratio))
        img = img.resize(new_size, Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        
        lbl = tk.Label(win, image=photo, bg="#2d3436")
        lbl.image = photo
        lbl.pack(padx=20, pady=20)
        
        tk.Button(win, text="关闭", command=win.destroy, bg="#636e72", fg="white").pack(pady=10)

# ── 主应用 ───────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("拼豆豆仓管理工具 v1.8 (多图版)")
        self.geometry("1560x880")
        self.minsize(900, 600)
        self.configure(bg="#1e272e")

        if not RAW:
            messagebox.showerror("启动失败", "配置文件加载失败。")
            self.destroy()
            return

        self.db = BeadDB()
        self._all, self._visible, self._selected, self._filter_id = [], [], None, None
        self.search_var, self.cat_var = tk.StringVar(), tk.StringVar(value="全部")
        self.search_var.trace_add("write", lambda *_: self._schedule_filter())
        self.cat_var.trace_add("write", lambda *_: self._schedule_filter())

        self._build_ui()
        self._load()

    def _build_ui(self):
        self._build_toolbar()
        self._build_main()
        self._build_statusbar()

    def _build_toolbar(self):
        bar = tk.Frame(self, bg="#2d3436", height=52)
        bar.pack(fill="x"); bar.pack_propagate(False)
        tk.Label(bar, text="🎯 拼豆豆仓管理", font=("SimHei",14,"bold"), bg="#2d3436", fg="white").pack(side="left", padx=14)
        tk.Label(bar, text="色系", bg="#2d3436", fg="#b2bec3", font=("SimHei",10)).pack(side="left", padx=(16,2))
        cats = ["全部"] + [CAT_NAMES[k] for k in CAT_ORDER]
        ttk.Combobox(bar, textvariable=self.cat_var, values=cats, state="readonly", width=11, font=("SimHei",10)).pack(side="left", padx=4, pady=10)
        tk.Label(bar, text="搜索", bg="#2d3436", fg="#b2bec3", font=("SimHei",10)).pack(side="left", padx=(12,2))
        tk.Entry(bar, textvariable=self.search_var, width=10, font=("SimHei",10)).pack(side="left", padx=4, pady=10)

        self.sort_btn_text = tk.StringVar(value="🔢 按色号排序")
        self.sort_btn = tk.Button(bar, textvariable=self.sort_btn_text, command=self._toggle_sort, bg="#6c5ce7", fg="white", relief="flat", font=("SimHei",9), padx=8, cursor="hand2")
        self.sort_btn.pack(side="right", padx=5, pady=10)

        btns = [
            ("📤 导出", self._export, "#00b894"), 
            ("📥 导入", self._import, "#0984e3"),
            ("⚠️ 低库存", self._show_low, "#e17055"), 
            ("📋 变更记录", self._show_history, "#6c5ce7"),
            ("📚 进出库日志", self._show_logs, "#fdcb6e"),
            ("🔄 批量设值", self._batch_set, "#a29bfe"), 
            ("🛒 极速补货", self._restock, "#00b894"), 
            ("⚡ 极速扣除", self._deduct, "#fd79a8"),
        ]
        for txt, cmd, bg in reversed(btns):
            tk.Button(bar, text=txt, command=cmd, bg=bg, fg="white", relief="flat", font=("SimHei",9), padx=8, cursor="hand2").pack(side="right", padx=5, pady=10)

    def _build_main(self):
        pane = tk.PanedWindow(self, orient="horizontal", sashwidth=6, bg="#636e72", sashrelief="flat")
        pane.pack(fill="both", expand=True)
        left = tk.Frame(pane, bg="#2d3436")
        pane.add(left, minsize=800, width=1280)
        self.cc = CardCanvas(left, self._select, bg="#2d3436", highlightthickness=0)
        vsc = ttk.Scrollbar(left, orient="vertical", command=self.cc.yview)
        self.cc.configure(yscrollcommand=vsc.set)
        vsc.pack(side="right", fill="y")
        self.cc.pack(fill="both", expand=True)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"): self.cc.bind(seq, self._scroll)
        right = tk.Frame(pane, bg="#f5f6fa", width=270)
        pane.add(right, minsize=240)
        self._build_detail(right)

    def _scroll(self, e):
        d = -1 if (e.delta > 0 if hasattr(e,"delta") else e.num == 4) else 1
        self.cc.yview_scroll(d, "units")

    def _build_detail(self, parent):
        self.ph = tk.Label(parent, text="← 点击色卡\n查看/编辑库存", font=("SimHei",12), fg="#bdc3c7", bg="#f5f6fa")
        self.ph.place(relx=.5, rely=.4, anchor="center")
        self.dc = tk.Frame(parent, bg="#f5f6fa")
        self.swatch = tk.Label(self.dc, width=18, height=5, relief="flat", bd=0)
        self.swatch.pack(padx=24, pady=(20,8), fill="x")
        self.lbl_code = tk.Label(self.dc, text="", font=("Consolas",18,"bold"), bg="#f5f6fa", fg="#2d3436")
        self.lbl_code.pack()
        self.lbl_hex = tk.Label(self.dc, text="", font=("Consolas",10), fg="#636e72", bg="#f5f6fa")
        self.lbl_hex.pack()
        self.lbl_cat = tk.Label(self.dc, text="", font=("SimHei",10), fg="#2d3436", bg="#f5f6fa")
        self.lbl_cat.pack(pady=4)
        ttk.Separator(self.dc).pack(fill="x", padx=16, pady=8)
        tk.Label(self.dc, text="库存数量", font=("SimHei",10,"bold"), bg="#f5f6fa").pack()
        row = tk.Frame(self.dc, bg="#f5f6fa"); row.pack(pady=6)
        tk.Button(row, text="−", font=("Arial",14,"bold"), width=3, bg="#e74c3c", fg="white", relief="flat", command=self._dec, cursor="hand2").pack(side="left", padx=3)
        self.qty_var = tk.IntVar(value=0)
        tk.Spinbox(row, textvariable=self.qty_var, from_=0, to=999999, width=9, font=("Arial",13), justify="center").pack(side="left")
        tk.Button(row, text="+", font=("Arial",14,"bold"), width=3, bg="#27ae60", fg="white", relief="flat", command=self._inc, cursor="hand2").pack(side="left", padx=3)
        tk.Button(self.dc, text="💾 快速保存", command=self._save_qty, bg="#2980b9", fg="white", relief="flat", font=("SimHei",10), cursor="hand2", pady=5).pack(fill="x", padx=20, pady=6)
        ttk.Separator(self.dc).pack(fill="x", padx=16, pady=6)
        row2 = tk.Frame(self.dc, bg="#f5f6fa"); row2.pack(fill="x", padx=20)
        tk.Label(row2, text="预警阈值", font=("SimHei",9,"bold"), bg="#f5f6fa").pack(side="left")
        self.thresh_var = tk.IntVar(value=50)
        tk.Spinbox(row2, textvariable=self.thresh_var, from_=0, to=9999, width=7, font=("Arial",11), justify="center").pack(side="right")
        tk.Label(self.dc, text="备注", font=("SimHei",9,"bold"), bg="#f5f6fa", anchor="w").pack(fill="x", padx=20, pady=(10,2))
        self.notes = tk.Text(self.dc, height=3, width=24, font=("SimHei",10), relief="groove", bd=1, wrap="word")
        self.notes.pack(padx=16, pady=2)
        tk.Button(self.dc, text="✅ 保存全部", command=self._save_all, bg="#16a085", fg="white", relief="flat", font=("SimHei",10), cursor="hand2", pady=5).pack(fill="x", padx=20, pady=10)

    def _build_statusbar(self):
        bar = tk.Frame(self, bg="#2d3436", height=28)
        bar.pack(fill="x", side="bottom"); bar.pack_propagate(False)
        self.status = tk.Label(bar, text="", bg="#2d3436", fg="#b2bec3", font=("SimHei",9))
        self.status.pack(side="left", padx=12, pady=4)

    def _load(self):
        self._all = self.db.get_all()
        self._do_filter()

    def _schedule_filter(self):
        if self._filter_id: self.after_cancel(self._filter_id)
        self._filter_id = self.after(150, self._do_filter)

    def _do_filter(self):
        q = self.search_var.get().strip().lower()
        rc = self.cat_var.get()
        cl = None if rc == "全部" else rc[0]
        filtered = [d for d in self._all if (not q or q in d["code"].lower()) and (cl is None or d["cat"] == cl)]
        self._visible = sorted(filtered, key=sort_key)
        self.cc.load(self._visible, self._selected)
        self._update_status()

    def _toggle_sort(self):
        global SORT_MODE
        if SORT_MODE == 'code':
            SORT_MODE = 'qty'
            self.sort_btn_text.set("📉 按库存排序")
            self.sort_btn.configure(bg="#e17055")
        else:
            SORT_MODE = 'code'
            self.sort_btn_text.set("🔢 按色号排序")
            self.sort_btn.configure(bg="#6c5ce7")
        self._do_filter()

    def _update_data_cache(self, code: str, d: dict):
        for lst in (self._all, self._visible):
            for i, x in enumerate(lst):
                if x["code"] == code: lst[i] = d; break

    def _select(self, code: str):
        self._selected = code
        self.cc.select(code)
        d = self.db.get_one(code)
        if not d: return
        self.ph.place_forget()
        self.dc.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.swatch.configure(bg=d["hex"])
        self.lbl_code.configure(text=d["code"])
        self.lbl_hex.configure(text=d["hex"].upper())
        self.lbl_cat.configure(text=CAT_NAMES.get(d["cat"], d["cat"]))
        self.qty_var.set(d["qty"])
        self.thresh_var.set(d["threshold"])
        self.notes.delete("1.0","end")
        self.notes.insert("1.0", d["notes"] or "")

    def _inc(self): self.qty_var.set(self.qty_var.get() + 1)
    def _dec(self): self.qty_var.set(max(0, self.qty_var.get() - 1))
    def _save_qty(self):
        if not self._selected: return
        self.db.update(self._selected, qty=self.qty_var.get())
        d = self.db.get_one(self._selected)
        self._update_data_cache(self._selected, d)
        self.cc.update_card(self._selected, d)
        self._update_status()
    def _save_all(self):
        if not self._selected: return
        self.db.update(self._selected, qty=self.qty_var.get(), threshold=self.thresh_var.get(), notes=self.notes.get("1.0","end").strip())
        d = self.db.get_one(self._selected)
        self._update_data_cache(self._selected, d)
        self.cc.update_card(self._selected, d)
        self._update_status()
        messagebox.showinfo("已保存", f"{self._selected} 已更新")

    def _update_status(self):
        s = self.db.stats()
        lowest = self.db.get_lowest(3)
        low_msg = ""
        if lowest:
            parts = [f"{code}({q})" for code, q in lowest if q > 0]
            zeros = [code for code, q in lowest if q == 0]
            if zeros: low_msg = f"🚫 缺货: {', '.join(zeros)}"
            elif parts: low_msg = f"⚠️ 极少: {', '.join(parts)}"
        mode_txt = " [库存排序]" if SORT_MODE == 'qty' else ""
        self.status.configure(text=f"共 {s['total']} 色 | 总库存 {s['sum_qty']:,} | ⚠️ {s['low']} | 🚫 {s['zero']} | {low_msg}{mode_txt}")

    def _deduct(self):
        FastDeductDialog(self, self.db, self._all, self._load)

    def _restock(self):
        FastRestockDialog(self, self.db, self._all, self._load)

    def _show_logs(self):
        ProjectLogViewer(self, self.db)

    def _export(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")], title="导出")
        if path: self.db.export_csv(path); messagebox.showinfo("完成", f"已保存: {path}")
    def _import(self):
        path = filedialog.askopenfilename(filetypes=[("CSV","*.csv")], title="导入")
        if path:
            try: n = self.db.import_csv(path); messagebox.showinfo("完成", f"导入 {n} 条"); self._load()
            except Exception as e: messagebox.showerror("错误", str(e))
    def _show_low(self):
        data = self.db.get_all()
        zero = [d for d in data if d["qty"] == 0]
        low = [d for d in data if 0 < d["qty"] <= d["threshold"]]
        win = tk.Toplevel(self); win.title("低库存"); win.geometry("500x400"); win.configure(bg="white")
        tk.Label(win, text="⚠️ 低库存 / 缺货", font=("SimHei", 12, "bold"), bg="white").pack(pady=10)
        tree = ttk.Treeview(win, columns=("c","q","t"), show="headings", height=15)
        tree.heading("c", text="色号"); tree.column("c", width=80)
        tree.heading("q", text="库存"); tree.column("q", width=80)
        tree.heading("t", text="阈值"); tree.column("t", width=80)
        for d in sorted(zero+low, key=lambda x: x["qty"]):
            tree.insert("", "end", values=(d["code"], d["qty"], d["threshold"]), tags=("z" if d["qty"]==0 else "l",))
        tree.tag_configure("z", foreground="red"); tree.tag_configure("l", foreground="orange")
        tree.pack(fill="both", expand=True, padx=10)
    def _show_history(self):
        if not self._selected: messagebox.showinfo("提示", "请先选色号"); return
        logs = self.db.get_history_logs(code=self._selected, limit=50)
        win = tk.Toplevel(self); win.title(f"历史 - {self._selected}"); win.geometry("600x400"); win.configure(bg="white")
        tk.Label(win, text=f"📋 {self._selected} 变动记录", font=("SimHei", 12, "bold"), bg="white").pack(pady=10)
        tree = ttk.Treeview(win, columns=("t", "type", "proj", "o", "n", "d"), show="headings", height=15)
        tree.heading("t", text="时间"); tree.column("t", width=120)
        tree.heading("type", text="类型"); tree.column("type", width=50, anchor="center")
        tree.heading("proj", text="来源/作品"); tree.column("proj", width=100)
        tree.heading("o", text="原"); tree.column("o", width=40)
        tree.heading("n", text="新"); tree.column("n", width=40)
        tree.heading("d", text="变动"); tree.column("d", width=50)
        for log in logs:
            d = log["new_qty"] - log["old_qty"]
            sign = "+" if d > 0 else ""
            type_disp = "🛒" if log["type"]=="restock" else "⚡"
            proj = log["project"] if log["project"] else "-"
            tag = "in" if log["type"]=="restock" else "out"
            tree.insert("", "end", values=(log["ts"][:16], type_disp, proj, log["old_qty"], log["new_qty"], f"{sign}{d}"), tags=(tag,))
        tree.tag_configure("in", foreground="#00b894")
        tree.tag_configure("out", foreground="#d63031")
        tree.pack(fill="both", expand=True, padx=10)
    def _batch_set(self):
        choices = ["缺货置数", "低库存置数", "当前筛选置数", "全量置数"]
        win = tk.Toplevel(self); win.title("批量设置"); win.geometry("300x200"); win.configure(bg="white")
        tk.Label(win, text="选择范围", font=("SimHei", 11), bg="white").pack(pady=5)
        cv = tk.IntVar()
        for i, t in enumerate(choices): tk.Radiobutton(win, text=t, variable=cv, value=i, bg="white").pack(anchor="w", padx=20)
        def run():
            val = simpledialog.askinteger("数量", "目标数量?", parent=win)
            if val is None: return
            all_d = self.db.get_all()
            targets = {}
            if cv.get()==0: targets = {d["code"]:val for d in all_d if d["qty"]==0}
            elif cv.get()==1: targets = {d["code"]:val for d in all_d if 0<d["qty"]<=d["threshold"]}
            elif cv.get()==2: targets = {d["code"]:val for d in self._visible}
            else: targets = {d["code"]:val for d in all_d}
            if targets and messagebox.askyesno("确认", f"设置 {len(targets)} 项?", parent=win):
                now = datetime.now().isoformat()
                with self.db._conn() as cx:
                    for code, qty in targets.items():
                        old = cx.execute("SELECT qty FROM beads WHERE code=?",(code,)).fetchone()
                        if old:
                            cx.execute("INSERT INTO history(code,old_qty,new_qty,ts,project_name,notes,image_data,type,price) VALUES(?,?,?,?,'','[]','deduct',0)", (code, old[0], qty, now, ''))
                        cx.execute("UPDATE beads SET qty=?,updated=? WHERE code=?",(qty,now,code))
                self._load(); win.destroy(); messagebox.showinfo("完成", "已更新")
        tk.Button(win, text="执行", command=run, bg="#0984e3", fg="white").pack(pady=10)

if __name__ == "__main__":
    App().mainloop()