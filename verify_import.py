
try:
    import requests
    print(f"Successfully imported requests version: {requests.__version__}")
    from streamlit_gsheets import GSheetsConnection
    print("Successfully imported GSheetsConnection from streamlit_gsheets")
except ImportError as e:
    print(f"Import failed: {e}")
except Exception as e:
    print(f"An error occurred: {e}")
