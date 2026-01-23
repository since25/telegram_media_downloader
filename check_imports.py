try:
    from module.bot import download_from_bot
    print("✓ Successfully imported download_from_bot")
except Exception as e:
    print(f"✗ Failed to import download_from_bot: {e}")
    import traceback
    traceback.print_exc()



try:
    from utils.format import extract_info_from_link
    print("✓ Successfully imported extract_info_from_link")
except Exception as e:
    print(f"✗ Failed to import extract_info_from_link: {e}")
    import traceback
    traceback.print_exc()