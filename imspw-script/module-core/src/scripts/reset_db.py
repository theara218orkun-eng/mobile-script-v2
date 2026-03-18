import sys
import os

# Ensure we can import aid_core if run directly
script_dir = os.path.dirname(os.path.abspath(__file__))
module_core_src = os.path.abspath(os.path.join(script_dir, "../../"))
if module_core_src not in sys.path:
    sys.path.insert(0, module_core_src)

from aid_core.db.database import sync_engine
from aid_core.db.models import Base

def reset_db(confirm=False):
    print("WARNING: This will DROP ALL DATA in the database.")
    print(f"Target DB: {sync_engine.url}")
    
    if not confirm:
        user_input = input("Type 'yes' to confirm: ")
        if user_input != "yes":
            print("Aborted.")
            return

    Base.metadata.drop_all(sync_engine)
    Base.metadata.create_all(sync_engine)
    print("[OK] Database reset complete.")

if __name__ == "__main__":
    import sys
    # Allow non-interactive mode with --yes flag
    if "--yes" in sys.argv or "-y" in sys.argv:
        reset_db(confirm=True)
    else:
        reset_db()
