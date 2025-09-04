from multiprocessing import freeze_support
from aduib_mcp_router.app import main

if __name__ == '__main__':
    freeze_support()
    main()