import sys
import os
from sqlalchemy import select, text

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

script_dir = os.path.dirname(os.path.abspath(__file__))
module_core_src = os.path.abspath(os.path.join(script_dir, "../../"))
if module_core_src not in sys.path:
    sys.path.insert(0, module_core_src)

from aid_core.db.database import SessionLocal
from aid_core.db.models import AgentAccount

def seed_agents():
    db = SessionLocal()
    try:
        db.execute(text("TRUNCATE TABLE agent_account RESTART IDENTITY CASCADE"))
        db.commit()
        
        agents_to_create = [
            {
                "name": "总接待",
                "role": "receptionist",
                "shift_hour": [1, 2, 3],
                "device_ip": "100.68.130.108",
                "device_serial_id": "c206d055",
                "whatsapp": {"account": "855962197645", "name": "WenDaoJuKH"},
                "status": "offline",
                "config": {
                    "message_jiedai_default": [
                        "https://t.me/c/3592050648/67",
                        "https://t.me/c/3592050648/68",
                        "https://t.me/c/3592050648/69",
                    ],
                    "message_majing_want_subscription": "https://t.me/c/3592050648/232",
                    "message_bojing_want_subscription": "https://t.me/c/3592050648/247",
                    "message_majing_country_selection": "https://t.me/c/3592050648/251",
                    "message_group_wait": "https://t.me/c/3592050648/249",
                    "message_group_created": "https://t.me/c/3592050648/234",
                }
            },
            {
                "name": "管理员01",
                "role": "admin",
                "shift_hour": [1, 2, 3],
                "device_ip": "100.77.197.88",
                "device_serial_id": "d8a1c24",
                "whatsapp": {"account": "855967567027", "name": "Qk1"},
                "status": "offline"
            },
            {
                "name": "管理员02",
                "role": "admin",
                "shift_hour": [1, 2, 3],
                "device_ip": "100.118.208.104",
                "device_serial_id": "3b097d1b",
                "whatsapp": {"account": "855963831845", "name": "Qk2"},
                "status": "offline"
            },
            {
                "name": "管理员03",
                "role": "admin",
                "shift_hour": [1, 2, 3],
                "device_ip": "100.97.217.42",
                "device_serial_id": "e84e7a9a",
                "whatsapp": {"account": "855963150488", "name": "Qk3"},
                "status": "offline"
            },
        ]

        for agent_data in agents_to_create:
            stmt = select(AgentAccount).where(AgentAccount.name == agent_data["name"])
            existing = db.execute(stmt).scalar_one_or_none()
            
            if not existing:
                print(f"Creating {agent_data['name']}...")
                new_agent = AgentAccount(**agent_data)
                db.add(new_agent)
            else:
                print(f"Agent {agent_data['name']} already exists.")
        
        db.commit()
        print("[OK] Agent seeding complete.")
        
    except Exception as e:
        print(f"[ERROR] Error seeding agents: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_agents()
