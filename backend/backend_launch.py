"""Frozen headless entry. WPF starts it with redirected pipes and CREATE_NO_WINDOW."""
import multiprocessing
import os
import sys
# The launcher lives in backend/, but the `studio` package lives at the repo root.
# Running `python backend/backend_launch.py` puts backend/ (not the root) on sys.path,
# so anchor the root explicitly before importing studio. Harmless in frozen mode
# (PyInstaller provides studio via hiddenimports and ignores sys.path inserts).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if __name__ == '__main__':
    multiprocessing.freeze_support()
    if '--worker' in sys.argv:
        from studio.worker import main
        raise SystemExit(main(sys.argv[sys.argv.index('--worker')+1]))
    elif '--bridge' in sys.argv:
        # BridgeClient launches the frozen backend with --bridge. Handle it explicitly so the
        # bridge is started by intent, not by falling through the argument chain by accident.
        from studio.bridge import main
        raise SystemExit(main())
    elif len(sys.argv)>2 and sys.argv[1]=='-m':
        import runpy
        module=sys.argv[2];sys.argv=sys.argv[2:]
        runpy.run_module(module,run_name='__main__',alter_sys=True)
    elif len(sys.argv)>1 and sys.argv[1].endswith('.py'):
        import runpy
        script=sys.argv[1];sys.argv=sys.argv[1:]
        runpy.run_path(script,run_name='__main__')
    else:
        from studio.bridge import main
        raise SystemExit(main())
