import logging
import threading
import time

import uiautomator2 as u2

from services.im_service import IMService

logger = logging.getLogger(__name__)

class WhatsAppService(IMService):
    def __init__(self):
        self.package_name = "com.whatsapp"

    def connect_device(self, device_ip: str):
        """Standardized connection to device via u2."""
        try:
            logger.info(f"[{device_ip}] [WhatsAppService] Connecting to u2...")
            d = u2.connect(device_ip)
            return d
        except Exception as e:
            logger.error(f"[{device_ip}] Failed to connect to device via u2: {e}")
            raise

    def _search_chat(self, d, target_name):
        """Helper to search and open a chat."""
        if d(resourceId=f"{self.package_name}:id/search_icon").exists:
            d(resourceId=f"{self.package_name}:id/search_icon").click()
        time.sleep(1)

        if d(className="android.widget.EditText").wait(timeout=5):
            d(className="android.widget.EditText").set_text(target_name)
        time.sleep(1)
        
        d(text=target_name).click()
        time.sleep(1)

    def send_message(self, device_ip: str, group_name: str, message: str, d=None):
        """
        Sends a message to a WhatsApp group using robust UI automation.
        Includes cold start, search with fallback, and verification.
        """
        if d is None:
            d = self.connect_device(device_ip)

        logger.info(f"[{device_ip}] [WhatsAppService] Sending to group '{group_name}'")
        d.app_start(self.package_name, stop=True)
        time.sleep(10)

        self._search_chat(d, group_name)
        time.sleep(2)  # Wait for chat to open
        
        # Verify we're in chat
        if not d(resourceId=f"{self.package_name}:id/entry").exists:
            logger.error(f"[{device_ip}] Not in chat view")
            d.app_start("jp.naver.line.android", stop=False)
            return
        
        success = self._send_text(d, message)
        if success:
            logger.info(f"[{device_ip}] [WhatsAppService] Message sent to '{group_name}'")
        else:
            logger.error(f"[{device_ip}] [WhatsAppService] Failed to send to '{group_name}'")
        # Don't switch to LINE - stay in WhatsApp for emulator
        # d.app_start("jp.naver.line.android", stop=False)

    def send_messages(self, device_ip: str, group_name: str, messages: list[str], d=None):
        """
        Sends multiple messages to a group in a single session.
        """
        if d is None:
            d = self.connect_device(device_ip)
        logger.info(f"[{device_ip}] [WhatsAppService] Sending {len(messages)} messages to group '{group_name}'")
        d.app_start(self.package_name, stop=True)
        time.sleep(10)
        
        self._search_chat(d, group_name)
        for msg in messages:
            try:
                success = self._send_text(d, msg)
                if not success:
                    logger.warning(f"[{device_ip}] Failed to send message segment to '{group_name}'")
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"[{device_ip}] Exception sending message segment to '{group_name}': {e}")
                time.sleep(1)
            
        logger.info(f"[{device_ip}] [WhatsAppService] Bulk messages sent to '{group_name}'")
        # Don't switch to LINE - stay in WhatsApp for emulator
        # d.app_start("jp.naver.line.android", stop=False)

    def send_messages_to_groups(self, device_ip: str, group_names: list[str], messages: list[str], d=None):
        """
        Sends multiple messages to multiple groups in a single app session.
        Optimized for bulk sending to many groups from one admin.
        """
        if d is None:
            d = self.connect_device(device_ip)
        logger.info(f"[{device_ip}] [WhatsAppService] Bulk sending to {len(group_names)} groups...")
        
        # Start app once
        d.app_start(self.package_name, stop=True)
        time.sleep(4)
        
        # Ensure we are on main screen (search icon visible)
        for _ in range(3):
            if d(resourceId=f"{self.package_name}:id/search_icon").exists:
                break
            d.press("back")
            time.sleep(1)

        for group_name in group_names:
            try:
                logger.info(f"[{device_ip}] [WhatsAppService] Target Group: '{group_name}'")
                self._search_chat(d, group_name)
                
                for msg in messages:
                    self._send_text(d, msg)
                    time.sleep(0.3)
                
                logger.info(f"[{device_ip}] [WhatsAppService] Done with '{group_name}'")
                
                # Navigate back to list for next search
                d.press("back")
                time.sleep(1)
                
                # If we are stuck in search mode, press back again
                if not d(resourceId=f"{self.package_name}:id/search_icon").exists:
                     d.press("back")
                     time.sleep(1)
                     
            except Exception as e:
                logger.error(f"[{device_ip}] [WhatsAppService] Error sending to '{group_name}': {e}")
                # Try to recover to main screen
                d.app_start(self.package_name)
                time.sleep(2)
                continue
                
        logger.info(f"[{device_ip}] [WhatsAppService] Bulk send complete.")
    
    def get_invite_link(self, device_ip: str, group_name: str, d=None) -> str:
        """
        Retrieves the invite link for a group.
        """
        try:
            if d is None:
                d = self.connect_device(device_ip)
            logger.debug(f"[{device_ip}] [WhatsAppService] Getting invite link for group '{group_name}'")
            d.app_start(self.package_name, stop=True)
            time.sleep(3)
            
            self._search_chat(d, group_name)
            
            if d(resourceId=f"{self.package_name}:id/conversation_contact_name").exists:
                d(resourceId=f"{self.package_name}:id/conversation_contact_name").click()
            time.sleep(1)
            
            return self._get_invite_link(d)
            
        except Exception as e:
            logger.error(f"[{device_ip}] Error getting invite link: {e}")
            raise

    def promote_admin(self, device_ip: str, group_name: str, admin_names: list[str], d=None):
        """
        Promotes specified participants to admin.
        """
        try:
            if d is None:
                d = self.connect_device(device_ip)
            logger.debug(f"[{device_ip}] [WhatsAppService] Promoting admins to group '{group_name}'")
            
            if not d(text=group_name).exists and not d(resourceId=f"{self.package_name}:id/conversation_contact_name").exists:
                self._search_chat(d, group_name)
                d(resourceId=f"{self.package_name}:id/conversation_contact_name").click()
            elif d(resourceId=f"{self.package_name}:id/conversation_contact_name").exists:
                d(resourceId=f"{self.package_name}:id/conversation_contact_name").click()
                
            time.sleep(1)
            self._navigate_to_admins_and_promote(d, admin_names)
            
        except Exception as e:
            logger.error(f"[{device_ip}] Error promoting admin: {e}")
            raise

    def create_group(self, device_ip: str, group_name: str, accounts: list[str], d=None):
        """
        Creates a new group with the specified accounts.
        """
        try:
            if d is None:
                d = self.connect_device(device_ip)
            logger.debug(f"[{device_ip}] [WhatsAppService] Creating group '{group_name}' with accounts: {accounts}")
            d.app_start(self.package_name, stop=True)
            time.sleep(5)

            if d(resourceId=f"{self.package_name}:id/fab").exists:
                d(resourceId=f"{self.package_name}:id/fab").click()
            time.sleep(1)

            if d(text="New group").wait(timeout=10):
                d(text="New group").click()
            else:
                raise Exception("Could not find 'New group' button")
            time.sleep(2)

            # 3. Add Participants
            for acc in accounts:
                logger.info(f"Adding participant: {acc}")
                # Click search if input not visible
                search_field = d(resourceId=f"{self.package_name}:id/search_src_text")
                if not search_field.exists:
                    search_btn = d(resourceId=f"{self.package_name}:id/menuitem_search")
                    if search_btn.exists:
                        search_btn.click()
                    else:
                        # Fallback to general search icon ID
                        d(resourceId=f"{self.package_name}:id/search_icon").click()
                
                time.sleep(1)
                search_field = d(resourceId=f"{self.package_name}:id/search_src_text")
                if search_field.wait(timeout=10):
                    search_field.set_text(acc)
                    time.sleep(1)
                    
                    # Wait for contact and click
                    contact_row = d(resourceId=f"{self.package_name}:id/chat_able_contacts_row_name", text=acc)
                    if contact_row.wait(timeout=10):
                        contact_row.click()
                        time.sleep(0.5)
                    elif d(text=acc).exists:
                        d(text=acc).click()
                        time.sleep(0.5)
                    else:
                        logger.warning(f"Could not find contact '{acc}' in search results")
                else:
                    logger.warning(f"Search field not found for contact '{acc}'")

            # 4. Click Next
            next_btn = d(resourceId=f"{self.package_name}:id/next_btn")
            if next_btn.wait(timeout=10):
                next_btn.click()
            else:
                raise Exception("Next button not found after adding participants")
            time.sleep(2)

            # 5. Set Group Name
            name_field = d(resourceId=f"{self.package_name}:id/group_name")
            if name_field.wait(timeout=10):
                name_field.set_text(group_name)
                time.sleep(1)
            else:
                # Fallback to first EditText
                d(className="android.widget.EditText").set_text(group_name)
                time.sleep(1)

            # 6. Click OK/Create
            ok_btn = d(resourceId=f"{self.package_name}:id/ok_btn")
            if ok_btn.wait(timeout=10):
                ok_btn.click()
            else:
                raise Exception("Create/OK button not found")
            
            logger.debug(f"[{device_ip}] [WhatsAppService] Group '{group_name}' created successfully")
            time.sleep(3)
            
            # Open group info to get invite link
            d(resourceId=f"{self.package_name}:id/conversation_contact_name").click()
            time.sleep(1)
            invite_link = self._get_invite_link(d)
            
            # Start background task for admin promotion and cleanup
            bg_thread = threading.Thread(target=self._promote_and_cleanup, args=(d, accounts))
            bg_thread.start()

            return {
                "invite_link": invite_link,
                "status": "success"
            }
            
        except Exception as e:
            logger.error(f"[{device_ip}] Error creating group: {e}")
            raise

    def _promote_and_cleanup(self, d, accounts):
        """
        Background task to promote admins and close the app.
        """
        try:
            logger.info("[WhatsAppService-BG] Starting background admin promotion...")
            self._navigate_to_admins_and_promote(d, accounts)
            logger.info("[WhatsAppService-BG] Admin promotion finished. Closing app...")
            time.sleep(1)
            d.app_stop(self.package_name)
            logger.info("[WhatsAppService-BG] App closed. Background task complete.")
        except Exception as e:
            logger.error(f"[WhatsAppService-BG] Error in background task: {e}")


    def inspect_group(self, device_ip: str, group_name: str):
         """
         Inspects a group (e.g. checks admins).
         """
         pass

    # --- Helpers ---
    def _get_invite_link(self, d):
        try:
            if d(description="Invite").exists:
                d(description="Invite").click()
            time.sleep(0.5)
            
            link = None
            if d(resourceId="com.whatsapp:id/link").exists:
                link = d(resourceId="com.whatsapp:id/link").get_text()
            
            d.press("back")
            return link
        except Exception as e:
            logger.error(f"Error fetching link: {e}")
            return None

    def _navigate_to_admins_and_promote(self, d, admin_names: list[str]):
        if not self._scroll_to_click(d, [{"text": "Group permissions"}, {"description": "Group permissions"}]):
            pass 
        else:
            time.sleep(0.5)
            if not self._scroll_to_click(d, [{"text": "Edit group admins"}, {"description": "Edit group admins"}]):
                d.press("back")
            else:
                time.sleep(0.5)
                self._elevate_admins(d, admin_names)
                return

        self._elevate_admins(d, admin_names)

    def _elevate_admins(self, d, admin_names: list[str]):
        for name in admin_names:
             self._scroll_to_click(d, [{"text": name}])
        
        time.sleep(1)
        if d(resourceId=f"{self.package_name}:id/next_btn").exists:
            d(resourceId=f"{self.package_name}:id/next_btn").click()
        elif d(resourceId=f"{self.package_name}:id/ok_btn").exists:
            d(resourceId=f"{self.package_name}:id/ok_btn").click()

    def _scroll_to_click(self, d, targets, max_swipes=10):
        for i in range(max_swipes + 1):
            for target in targets:
                if d(**target).exists:
                    d(**target).click()
                    return True
            if i < max_swipes:
                d.swipe_ext("up", scale=0.8)
                time.sleep(0.3)
        return False

    def _send_text(self, d, message: str):
        """Helper to type and send text in an open chat."""
        try:
            # Find message input field
            entry_field = d(resourceId=f"{self.package_name}:id/entry")
            if not entry_field.exists:
                # Fallback: try description
                entry_field = d(description="Message")

            if entry_field.exists:
                # Clear any existing text first
                entry_field.click()
                time.sleep(0.5)

                # Set the message
                entry_field.set_text(message)
                time.sleep(1)  # Wait for text to be entered

                # Find and click send button - try multiple methods
                send_btn = None

                # Method 1: By resource ID
                send_btn = d(resourceId=f"{self.package_name}:id/send")

                # Method 2: By description
                if not send_btn.exists:
                    send_btn = d(description="Send")

                # Method 3: By content description containing "send"
                if not send_btn.exists:
                    send_btn = d(descriptionContains="Send")

                # Method 4: Try className with send description
                if not send_btn.exists:
                    send_btn = d(className="android.widget.ImageButton", description="Send")

                if send_btn.exists:
                    send_btn.click()
                    time.sleep(1)  # Wait for send to complete
                    logger.info(f"Message sent successfully")
                    return True
                else:
                    logger.warning(f"Send button not found. Available buttons:")
                    # Debug: log what buttons are available
                    try:
                        buttons = d(className="android.widget.ImageButton")
                        if buttons.exists:
                            logger.info(f"Found {buttons.count} ImageButtons")
                    except:
                        pass
                    return False
            else:
                logger.warning("Message entry field not found")
                return False
        except Exception as e:
            logger.error(f"Error in _send_text: {e}")
            return False

    def send_image(self, device_ip: str, target: str, image_path: str, caption: str = "", d=None):
        """
        Sends an image to a WhatsApp contact or group.
        target: phone number or group name
        image_path: path to image on device (e.g. /sdcard/Download/tmp.jpg)
        caption: optional caption
        """
        if d is None:
            d = self.connect_device(device_ip)

        logger.info(f"[{device_ip}] [WhatsAppService] Sending image '{image_path}' to '{target}'")

        try:
            d.app_start(self.package_name, stop=True)
            time.sleep(5)

            self._search_chat(d, target)
            time.sleep(1)

            if self._send_image(d, image_path, caption):
                logger.info(f"[{device_ip}] [WhatsAppService] Image sent to '{target}'")
            else:
                logger.error(f"[{device_ip}] Failed to send image to '{target}'")

        except Exception as e:
            logger.error(f"[{device_ip}] Error in send_image: {e}")
        finally:
            d.app_start("jp.naver.line.android", stop=False)

    def _send_image(self, d, image_path: str, caption: str = "") -> bool:
        """Helper to send an image via UI automation."""
        try:
            # Click attachment/camera button
            attach_btn = d(resourceId=f"{self.package_name}:id/attach_button")
            if not attach_btn.exists:
                attach_btn = d(description="Attach")
            if not attach_btn.exists:
                # Try camera button
                attach_btn = d(resourceId=f"{self.package_name}:id/camera_button")
            
            if not attach_btn.exists:
                logger.warning("Attach button not found")
                return False

            attach_btn.click()
            time.sleep(1)

            # Click Gallery/Document option
            gallery_btn = d(text="Gallery")
            if not gallery_btn.exists:
                gallery_btn = d(text="Image")
            if not gallery_btn.exists:
                gallery_btn = d(description="Gallery")
            if not gallery_btn.exists:
                # Try document option
                gallery_btn = d(text="Document")
            
            if gallery_btn.exists:
                gallery_btn.click()
            else:
                logger.warning("Gallery button not found")
                return False
            
            time.sleep(2)

            # Select image from gallery - click first image
            first_image = d(className="android.widget.ImageView")
            if first_image.exists:
                first_image.click()
                time.sleep(1)
            else:
                logger.warning("No images found in gallery")
                # Try to find by description
                image_item = d(descriptionContains="Image")
                if image_item.exists:
                    image_item.click()
                    time.sleep(1)
                else:
                    return False

            # Add caption if provided
            if caption:
                caption_input = d(className="android.widget.EditText")
                if caption_input.exists:
                    caption_input.set_text(caption)
                    time.sleep(0.5)

            # Click Send
            send_btn = d(resourceId=f"{self.package_name}:id/send")
            if not send_btn.exists:
                send_btn = d(description="Send")
            
            if send_btn.exists:
                send_btn.click()
                time.sleep(1)
                return True
            
            logger.warning("Send button not found for image")
            return False

        except Exception as e:
            logger.error(f"Error in _send_image: {e}")
            return False

whatsapp_service = WhatsAppService()
