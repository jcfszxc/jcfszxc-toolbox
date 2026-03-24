import tkinter as tk
from tkinter import ttk, messagebox

class HexConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("十六进制补码转换器")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        
        # 设置样式
        style = ttk.Style()
        style.configure('Title.TLabel', font=('Arial', 16, 'bold'))
        style.configure('Result.TLabel', font=('Arial', 12, 'bold'))
        
        self.create_widgets()
    
    def create_widgets(self):
        # 标题
        title_frame = ttk.Frame(self.root, padding="10")
        title_frame.pack(fill=tk.X)
        ttk.Label(title_frame, text="十六进制补码转十进制", 
                 style='Title.TLabel').pack()
        
        # 输入区域
        input_frame = ttk.LabelFrame(self.root, text="输入", padding="15")
        input_frame.pack(fill=tk.X, padx=20, pady=10)
        
        ttk.Label(input_frame, text="十六进制数:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.hex_entry = ttk.Entry(input_frame, width=30, font=('Courier', 12))
        self.hex_entry.grid(row=0, column=1, padx=10, pady=5)
        self.hex_entry.bind('<Return>', lambda e: self.convert())
        
        ttk.Label(input_frame, text="提示: 可以带0x前缀或不带", 
                 font=('Arial', 9), foreground='gray').grid(row=1, column=1, sticky=tk.W, padx=10)
        
        # 位数选择
        ttk.Label(input_frame, text="位数:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.bit_var = tk.StringVar(value="8")
        bit_frame = ttk.Frame(input_frame)
        bit_frame.grid(row=2, column=1, sticky=tk.W, padx=10, pady=5)
        
        for bits in ["8", "16", "32", "64"]:
            ttk.Radiobutton(bit_frame, text=f"{bits}位", variable=self.bit_var, 
                           value=bits).pack(side=tk.LEFT, padx=5)
        
        # 转换按钮
        button_frame = ttk.Frame(self.root, padding="10")
        button_frame.pack(fill=tk.X)
        
        ttk.Button(button_frame, text="转换", command=self.convert, 
                  width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="清空", command=self.clear, 
                  width=15).pack(side=tk.LEFT, padx=10)
        
        # 结果显示区域
        result_frame = ttk.LabelFrame(self.root, text="结果", padding="15")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # 十进制结果
        result_inner = ttk.Frame(result_frame)
        result_inner.pack(fill=tk.X, pady=5)
        ttk.Label(result_inner, text="十进制:").pack(side=tk.LEFT)
        self.decimal_result = ttk.Label(result_inner, text="", 
                                       style='Result.TLabel', foreground='blue')
        self.decimal_result.pack(side=tk.LEFT, padx=10)
        
        # 二进制显示
        ttk.Label(result_frame, text="二进制:").pack(anchor=tk.W, pady=(10, 5))
        self.binary_text = tk.Text(result_frame, height=3, width=60, 
                                   font=('Courier', 10), wrap=tk.WORD)
        self.binary_text.pack(fill=tk.X, pady=5)
        
        # 转换步骤
        ttk.Label(result_frame, text="转换步骤:").pack(anchor=tk.W, pady=(10, 5))
        self.steps_text = tk.Text(result_frame, height=8, width=60, 
                                 font=('Courier', 9), wrap=tk.WORD)
        self.steps_text.pack(fill=tk.BOTH, expand=True, pady=5)
    
    def convert(self):
        hex_str = self.hex_entry.get().strip()
        if not hex_str:
            messagebox.showwarning("警告", "请输入十六进制数！")
            return
        
        # 移除0x前缀
        if hex_str.lower().startswith('0x'):
            hex_str = hex_str[2:]
        
        # 验证输入
        try:
            hex_value = int(hex_str, 16)
        except ValueError:
            messagebox.showerror("错误", "无效的十六进制数！")
            return
        
        bits = int(self.bit_var.get())
        max_value = 2 ** bits
        
        # 确保值在范围内
        hex_value = hex_value % max_value
        
        # 转换为补码
        if hex_value >= max_value // 2:
            decimal_value = hex_value - max_value
        else:
            decimal_value = hex_value
        
        # 获取二进制表示
        binary_str = bin(hex_value)[2:].zfill(bits)
        
        # 显示结果
        self.decimal_result.config(text=str(decimal_value))
        
        # 显示二进制（每8位一组）
        binary_formatted = ' '.join([binary_str[i:i+8] for i in range(0, len(binary_str), 8)])
        self.binary_text.delete(1.0, tk.END)
        self.binary_text.insert(1.0, binary_formatted)
        
        # 显示转换步骤
        self.steps_text.delete(1.0, tk.END)
        steps = self.get_conversion_steps(hex_str, hex_value, decimal_value, bits, binary_str)
        self.steps_text.insert(1.0, steps)
    
    def get_conversion_steps(self, hex_str, hex_value, decimal_value, bits, binary_str):
        steps = f"输入: 0x{hex_str.upper()}\n"
        steps += f"位数: {bits}位\n"
        steps += f"范围: {-(2**(bits-1))} 到 {2**(bits-1)-1}\n\n"
        
        # 判断正负
        msb = int(binary_str[0])
        if msb == 0:
            steps += f"最高位为 0 → 正数\n"
            steps += f"直接转换: 0x{hex_str.upper()} = {hex_value} = {decimal_value}\n"
        else:
            steps += f"最高位为 1 → 负数\n"
            steps += f"原码: {hex_value}\n"
            
            # 取反加一的方法
            inverted = (2**bits - 1) - hex_value
            inverted_plus_one = inverted + 1
            steps += f"\n方法1 (取反加一):\n"
            steps += f"  取反: {inverted} (0x{inverted:0{bits//4}X})\n"
            steps += f"  加一: {inverted_plus_one} (0x{inverted_plus_one:0{bits//4}X})\n"
            steps += f"  结果: -{inverted_plus_one}\n"
            
            # 补码公式
            steps += f"\n方法2 (补码公式):\n"
            steps += f"  {hex_value} - {2**bits} = {decimal_value}\n"
        
        return steps
    
    def clear(self):
        self.hex_entry.delete(0, tk.END)
        self.decimal_result.config(text="")
        self.binary_text.delete(1.0, tk.END)
        self.steps_text.delete(1.0, tk.END)
        self.hex_entry.focus()

if __name__ == "__main__":
    root = tk.Tk()
    app = HexConverter(root)
    root.mainloop()