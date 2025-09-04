import asyncio
from multiprocessing import freeze_support


if __name__ == '__main__':
    freeze_support()
    from aduib_mcp_router.app import main
    asyncio.run(main())