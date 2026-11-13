"""Windows entry point; no private templates or external service credentials."""
from pathlib import Path
import sys,os,traceback
os.environ.setdefault('MPLCONFIGDIR',str(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Veylfit'/'cache'/'matplotlib'))

def main():
    if '--self-test' in sys.argv:
        from diagnostics import run
        output=Path(sys.argv[sys.argv.index('--self-test')+1])
        intake=Path(sys.argv[sys.argv.index('--test-intake')+1]) if '--test-intake' in sys.argv else None
        run(output,intake);return
    from desktop_app import main as desktop
    desktop()

if __name__=='__main__':
    try:main()
    except Exception:
        folder=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Veylfit'/'logs';folder.mkdir(parents=True,exist_ok=True)
        (folder/'last-error.txt').write_text(traceback.format_exc(),'utf-8')
        if '--self-test' not in sys.argv and '--check-startup' not in sys.argv:
            import tkinter as tk
            from tkinter import messagebox
            root=tk.Tk();root.withdraw();messagebox.showerror('映衣间启动未完成','错误已记录在本机：'+str(folder/'last-error.txt'));root.destroy()
        raise SystemExit(1)
