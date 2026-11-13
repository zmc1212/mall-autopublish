import sys

if __name__ == "__main__":
    # 更新进程必须在导入桌面端、Qt、WebView 和业务模块之前分流。
    if len(sys.argv) == 3 and sys.argv[1] == "--apply-update":
        from desktop.update_worker import main

        raise SystemExit(main(sys.argv[2]))
    from desktop.app import main

    raise SystemExit(main())
