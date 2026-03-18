import threading
import time
import logging
import frida
from queue import Queue

from frida_core.device_worker import DeviceWorker
from worker_registry import register_worker, unregister_worker

logger = logging.getLogger(__name__)

class DeviceSupervisor(threading.Thread):
    """
    Supervises the DeviceWorker, handling initialization, 
    connection, and restarts (self-healing) upon failure.
    """
    def __init__(self, device_id: str, package_name: str, bundle_content: str, incoming_queue: Queue):
        super().__init__()
        self.device_id = device_id
        self.package_name = package_name
        self.bundle_content = bundle_content
        self.incoming_queue = incoming_queue
        self.stop_event = threading.Event()
        self.worker = None

    def run(self):
        logger.info(f"Supervisor started for device: {self.device_id or 'USB'} package: {self.package_name}")
        
        while not self.stop_event.is_set():
            try:
                # 1. Connect to Frida Device
                frida_device = self._get_frida_device()
                logger.info(f"Frida Device Connected: {frida_device.name} ({frida_device.id})")

                # 2. Start Worker
                self.worker = DeviceWorker(
                    device=frida_device,
                    bundle=self.bundle_content,
                    target_package=self.package_name,
                    incoming_queue=self.incoming_queue
                )
                self.worker.start()
                register_worker(frida_device.id, self.package_name, self.worker)

                # 3. Monitor Worker
                while not self.stop_event.is_set() and self.worker.is_alive():
                    time.sleep(1)
                
                if not self.stop_event.is_set():
                    logger.warning("Worker thread died unexpectedly. Restarting in 5 seconds...")
                    time.sleep(5)

            except frida.ServerNotRunningError:
                 logger.error("Frida server is not running on the device. Retrying in 10 seconds...")
                 time.sleep(10)
            except frida.TransportError:
                 logger.error("Frida transport error (device disconnected?). Retrying in 10 seconds...")
                 time.sleep(10)
            except Exception as e:
                logger.error(f"Supervisor Error: {e}")
                logger.info("Retrying in 5 seconds...")
                time.sleep(5)
            finally:
                self._stop_worker()
                time.sleep(1) # Brief pause before next loop iteration

        logger.info("Supervisor stopped.")

    def _get_frida_device(self):
        if self.device_id:
            logger.debug(f"Getting Frida device {self.device_id}...")
            return frida.get_device(self.device_id)
        else:
            logger.debug("Getting first available USB Frida device...")
            return frida.get_usb_device()

    def _stop_worker(self):
        if self.worker:
            unregister_worker(self.device_id, self.package_name)
            if self.worker.is_alive():
                self.worker.stop()
                self.worker.join()
            self.worker = None

    def stop(self):
        """Stops the supervisor and the specific worker."""
        logger.info("Stopping supervisor...")
        self.stop_event.set()
        self._stop_worker()
