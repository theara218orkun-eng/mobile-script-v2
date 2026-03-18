/**
 * Open Messenger chat via Deep Link.
 * Actual input/send is done by messenger_service in Python.
 */
import Java from "frida-java-bridge";

export function send(userId, _message) {
	try {
		const Intent = Java.use("android.content.Intent");
		const Uri = Java.use("android.net.Uri");
		const uri = Uri.parse("fb-messenger://user-thread/" + userId);
		const intent = Intent.$new("android.intent.action.VIEW", uri);
		intent.addFlags(0x10000000);
		const ActivityThread = Java.use("android.app.ActivityThread");
		const ctx = ActivityThread.currentApplication().getApplicationContext();
		ctx.startActivity(intent);
		return Promise.resolve(true);
	} catch (e) {
		console.error("[messenger_message_sender] " + e);
		return Promise.resolve(false);
	}
}
