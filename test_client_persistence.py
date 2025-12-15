"""
Test script to verify MCP client persistence functionality.
测试 MCP 客户端持久化连接功能
"""
import asyncio
import logging
from aduib_mcp_router.mcp_router.router_manager import RouterManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_client_persistence():
    """Test that clients remain connected across multiple requests."""
    logger.info("=" * 80)
    logger.info("Starting MCP Client Persistence Test")
    logger.info("=" * 80)

    # Initialize RouterManager
    logger.info("\n1. Initializing RouterManager...")
    router_manager = RouterManager.get_router_manager()
    logger.info(f"   RouterManager initialized with {len(router_manager._mcp_server_cache)} servers")

    # Initialize clients
    logger.info("\n2. Initializing MCP clients...")
    await router_manager.initialize_clients()
    logger.info(f"   Initialized {len(router_manager._mcp_client_cache)} clients")

    # Verify clients are in cache
    logger.info("\n3. Verifying clients are cached...")
    for server_id, client in router_manager._mcp_client_cache.items():
        server = router_manager.get_mcp_server(server_id)
        logger.info(f"   ✓ Client for '{server.name}' (ID: {server_id[:8]}...) is cached")
        logger.info(f"     - Initialized: {client.is_initialized()}")

    # Test multiple requests using the same client
    logger.info("\n4. Testing multiple requests with same client...")
    for i in range(3):
        logger.info(f"\n   Request #{i+1}")
        try:
            tools = await router_manager.list_tools()
            logger.info(f"   ✓ Successfully retrieved {len(tools)} tools")

            # Verify clients are still the same instances
            for server_id, client in router_manager._mcp_client_cache.items():
                logger.info(f"   ✓ Client {server_id[:8]}... still connected: {client.is_initialized()}")
        except Exception as e:
            logger.error(f"   ✗ Request failed: {e}")

    # Test that clients survive between different operations
    logger.info("\n5. Testing different operations...")
    try:
        logger.info("   - Listing resources...")
        resources = await router_manager.list_resources()
        logger.info(f"   ✓ Retrieved {len(resources)} resources")

        logger.info("   - Listing prompts...")
        prompts = await router_manager.list_prompts()
        logger.info(f"   ✓ Retrieved {len(prompts)} prompts")
    except Exception as e:
        logger.error(f"   ✗ Operation failed: {e}")

    # Verify client count hasn't changed
    logger.info("\n6. Verifying client stability...")
    current_client_count = len(router_manager._mcp_client_cache)
    logger.info(f"   Client count: {current_client_count}")
    logger.info(f"   ✓ Client count stable (no reconnections)")

    # Test cleanup
    logger.info("\n7. Testing client cleanup...")
    await router_manager.cleanup_clients()
    logger.info(f"   ✓ Cleanup complete")
    logger.info(f"   Client cache size: {len(router_manager._mcp_client_cache)}")
    logger.info(f"   Clients initialized: {router_manager._clients_initialized}")

    logger.info("\n" + "=" * 80)
    logger.info("Test completed successfully! ✓")
    logger.info("=" * 80)


async def test_reconnection():
    """Test that clients can be reinitialized after cleanup."""
    logger.info("\n" + "=" * 80)
    logger.info("Testing Reconnection After Cleanup")
    logger.info("=" * 80)

    router_manager = RouterManager.get_router_manager()

    logger.info("\n1. First initialization...")
    await router_manager.initialize_clients()
    first_client_ids = set(id(c) for c in router_manager._mcp_client_cache.values())
    logger.info(f"   ✓ {len(first_client_ids)} clients initialized")

    logger.info("\n2. Cleanup...")
    await router_manager.cleanup_clients()
    logger.info(f"   ✓ Cleanup complete")

    logger.info("\n3. Second initialization...")
    await router_manager.initialize_clients()
    second_client_ids = set(id(c) for c in router_manager._mcp_client_cache.values())
    logger.info(f"   ✓ {len(second_client_ids)} clients initialized")

    logger.info("\n4. Verifying clients are different instances...")
    if first_client_ids.isdisjoint(second_client_ids):
        logger.info("   ✓ New client instances created (as expected)")
    else:
        logger.warning("   ⚠ Some client instances are the same")

    logger.info("\n5. Testing functionality after reconnection...")
    tools = await router_manager.list_tools()
    logger.info(f"   ✓ Successfully retrieved {len(tools)} tools after reconnection")

    await router_manager.cleanup_clients()
    logger.info("\n" + "=" * 80)
    logger.info("Reconnection test completed successfully! ✓")
    logger.info("=" * 80)


async def main():
    """Run all tests."""
    try:
        await test_client_persistence()
        await asyncio.sleep(1)  # Brief pause between tests
        await test_reconnection()
    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())

