"""Keep Windows shell snapping available on a pywebview frameless window."""

import ctypes
from ctypes import wintypes


def install_windows_snap(window) -> None:
    from maeumnarae.core.desktop import _maximized_work_area

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    comctl32 = ctypes.WinDLL('comctl32', use_last_error=True)
    result_type = ctypes.c_ssize_t
    subclass_proc = ctypes.WINFUNCTYPE(
        result_type, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
        wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
    comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, subclass_proc,
                                         ctypes.c_size_t, ctypes.c_size_t]
    comctl32.SetWindowSubclass.restype = wintypes.BOOL
    comctl32.RemoveWindowSubclass.argtypes = [wintypes.HWND, subclass_proc, ctypes.c_size_t]
    comctl32.RemoveWindowSubclass.restype = wintypes.BOOL
    comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
    comctl32.DefSubclassProc.restype = result_type
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    user32.SetWindowLongW.restype = wintypes.LONG
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.ReleaseCapture.argtypes = []
    user32.ReleaseCapture.restype = wintypes.BOOL

    @subclass_proc
    def window_proc(hwnd, message, wparam, lparam, subclass_id, reference):
        if message == 0x0083:  # WM_NCCALCSIZE: keep the entire window as client area.
            return 0
        if message == 0x0082:  # WM_NCDESTROY: detach before the handle is released.
            comctl32.RemoveWindowSubclass(hwnd, window_proc, subclass_id)
        return comctl32.DefSubclassProc(hwnd, message, wparam, lparam)

    def attach(*_):
        if window.native.IsDisposed or not window.native.IsHandleCreated:
            return
        hwnd = window.native.Handle.ToInt64()
        if not comctl32.SetWindowSubclass(hwnd, window_proc, 1, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        # WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_SYSMENU.
        # The subclass suppresses the visible standard frame, not these capabilities.
        style = user32.GetWindowLongW(hwnd, -16)
        ctypes.set_last_error(0)
        previous = user32.SetWindowLongW(hwnd, -16, style | 0x000F0000)
        if not previous and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        if not user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0037):
            raise ctypes.WinError(ctypes.get_last_error())

    def before_show():
        # pywebview loads pythonnet and WinForms after create_window returns.
        from System import Action
        from System.Windows.Forms import FormWindowState, Screen

        form = window.native
        # Keep the callback alive and reapply styles if WinForms recreates its HWND.
        window._snap_window_proc = window_proc
        def handle_created(*_):
            # WinForms resets style bits after HandleCreated during recreation.
            form.BeginInvoke(Action(attach))

        form.HandleCreated += handle_created
        attach()

        def update_work_area(*_):
            if form.WindowState == FormWindowState.Normal:
                form.MaximizedBounds = _maximized_work_area(Screen.FromControl(form))

        form.Move += update_work_area

    def start_window_move():
        from System import Action
        from System.Windows.Forms import Control, MouseButtons

        form = window.native

        def begin():
            if Control.MouseButtons != MouseButtons.Left:
                return
            user32.ReleaseCapture()
            # SC_MOVE | HTCAPTION enters the shell's modal move loop, including Aero Snap.
            user32.PostMessageW(form.Handle.ToInt64(), 0x0112, 0xF012, 0)

        form.Invoke(Action(begin))

    def install_drag():
        window.run_js("""
            (() => {
                if (window.__maeumnaraeNativeDrag) return;
                window.__maeumnaraeNativeDrag = true;
                let origin = null;
                document.addEventListener('mousedown', event => {
                    if (event.button !== 0 ||
                        !event.target.closest('.pywebview-drag-region')) return;
                    // Prevent pywebview's coordinate-based move handler from starting.
                    event.stopImmediatePropagation();
                    event.preventDefault();
                    origin = {x: event.screenX, y: event.screenY};
                }, true);
                document.addEventListener('mousemove', event => {
                    if (!origin) return;
                    if (!(event.buttons & 1)) { origin = null; return; }
                    if (Math.abs(event.screenX - origin.x) < 4 &&
                        Math.abs(event.screenY - origin.y) < 4) return;
                    origin = null;
                    window.pywebview.api.start_window_move();
                }, true);
                document.addEventListener('mouseup', () => { origin = null; }, true);
                window.addEventListener('blur', () => { origin = null; });
            })();
        """)

    window.expose(start_window_move)
    window.events.before_show += before_show
    window.events.loaded += install_drag
