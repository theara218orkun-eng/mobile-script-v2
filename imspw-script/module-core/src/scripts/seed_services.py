"""
Seed script for ServiceSubscription table
Creates default service subscription entries
"""
import asyncio
import sys
import os

# Add parent directory to path for direct execution
script_dir = os.path.dirname(os.path.abspath(__file__))
module_core_src = os.path.abspath(os.path.join(script_dir, "../../"))
if module_core_src not in sys.path:
    sys.path.insert(0, module_core_src)

from aid_core.db.database import AsyncSessionLocal
from aid_core.db.models import ServiceSubscription
from sqlalchemy.future import select

async def seed_services():
    """Seed the ServiceSubscription table with default services"""
    
    services = [
        {
            "name": "微博马经HK",
        },
        {
            "name": "微博马经JA",
        },
        {
            "name": "微博马经GB",
        },
        {
            "name": "微博马经AU",
        }
    ]
    
    async with AsyncSessionLocal() as session:
        try:
            for service_data in services:
                result = await session.execute(
                    select(ServiceSubscription).filter(
                        ServiceSubscription.name == service_data["name"]
                    )
                )
                existing = result.scalars().first()
                
                if existing:
                    print(f"✓ Service '{service_data['name']}' already exists (ID: {existing.id})")
                else:
                    service = ServiceSubscription(**service_data)
                    session.add(service)
                    await session.commit()
                    await session.refresh(service)
                    print(f"✓ Created service '{service.name}' (ID: {service.id})")
            
            print("\n✅ Service seeding completed successfully!")
            
        except Exception as e:
            print(f"❌ Error seeding services: {e}")
            await session.rollback()
            raise

if __name__ == "__main__":
    asyncio.run(seed_services())
