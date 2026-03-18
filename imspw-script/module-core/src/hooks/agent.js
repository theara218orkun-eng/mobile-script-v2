import Java from "frida-java-bridge";
import * as WAMsgListener from "./modules/wa_message_listener";
import * as LineMsgListener from "./modules/line_message_listener";
import * as LineMsgSender from "./modules/line_message_sender";
import * as WaMsgSender from "./modules/wa_message_sender";
import * as WaBusinessMsgSender from "./modules/wa_business_message_sender";
import * as MessengerMsgSender from "./modules/messenger_message_sender";

var targetPackage = "";
var hooksInstalled = false;

function installHooks() {
	if (hooksInstalled) return;
	setTimeout(function () {
		Java.perform(function () {
			try {
				var SQLiteDatabase = Java.use("android.database.sqlite.SQLiteDatabase");
				
				// Hook insertWithOnConflict (most common)
				SQLiteDatabase.insertWithOnConflict.overload(
					'java.lang.String', 'java.lang.String', 'android.content.ContentValues', 'int'
				).implementation = function (table, nullColumnHack, initialValues, conflictAlgorithm) {
					try {
						var dbInstance = Java.cast(this, SQLiteDatabase);
						handleInsert(dbInstance, table, initialValues);
					} catch (error) {
						console.log("[Frida] Hook Error: " + error);
					}
					return this.insertWithOnConflict(table, nullColumnHack, initialValues, conflictAlgorithm);
				};
				
				// Hook insert (alternative method)
				SQLiteDatabase.insert.overload(
					'java.lang.String', 'java.lang.String', 'android.content.ContentValues'
				).implementation = function (table, nullColumnHack, initialValues) {
					try {
						var dbInstance = Java.cast(this, SQLiteDatabase);
						handleInsert(dbInstance, table, initialValues);
					} catch (error) {
						console.log("[Frida] Hook Error: " + error);
					}
					return this.insert(table, nullColumnHack, initialValues);
				};
				
				hooksInstalled = true;
				console.log("[Frida] Hooks installed for " + targetPackage);
			} catch (e) {
				console.error("[Frida] Error installing hooks: " + e);
			}
		});
	}, 1000);
}

function handleInsert(dbInstance, table, initialValues) {
	try {
		if (targetPackage === "jp.naver.line.android") {
			const lineResult = LineMsgListener.init(dbInstance, table, initialValues);
			if (lineResult) send(lineResult);
		} else if (targetPackage === "com.whatsapp" || targetPackage === "com.whatsapp.w4b") {
			const waResult = WAMsgListener.init(dbInstance, initialValues);
			if (waResult) send(waResult);
		}
	} catch (error) {
		console.log("[Frida] HandleInsert Error: " + error);
	}
}

rpc.exports = {
	lineSend: function (userId, displayName, message) {
		return LineMsgSender.send(userId, displayName, message);
	},
	waSend: function (phoneNumber, message) {
		return WaMsgSender.send(phoneNumber, message);
	},
	waBusinessSend: function (phoneNumber, message) {
		return WaBusinessMsgSender.send(phoneNumber, message);
	},
	messengerSend: function (userId, message) {
		return MessengerMsgSender.send(userId, message);
	},
	setTargetPackage: function (pkg) {
		targetPackage = pkg;
		console.log("[Frida] Target package set to: " + targetPackage);
		installHooks();
	}
};
