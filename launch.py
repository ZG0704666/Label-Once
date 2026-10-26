import multiprocessing
import sys
if __name__ == '__main__':
    multiprocessing.freeze_support()
    if '--worker' in sys.argv:
        from studio.worker import main
        raise SystemExit(main(sys.argv[sys.argv.index('--worker')+1]))
    elif len(sys.argv) > 2 and sys.argv[1] == '-m':
        # Ultralytics DDP invokes sys.executable as a Python launcher.
        import runpy
        module=sys.argv[2];sys.argv=sys.argv[2:]
        runpy.run_module(module,run_name='__main__',alter_sys=True)
    elif len(sys.argv) > 1 and sys.argv[1].endswith('.py'):
        import runpy
        script=sys.argv[1];sys.argv=sys.argv[1:]
        runpy.run_path(script,run_name='__main__')
    else:
        from studio.app import main
        raise SystemExit(main())
