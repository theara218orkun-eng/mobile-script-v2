import Java from "frida-java-bridge";

const senderCache = new Map();

function resolveJidInfo(db, jidRowId, jidType = "person") {
	let info = { uuid: "", username: "", phone: "", type: jidType };
	if (!jidRowId) return info;

	let rowStr = jidRowId.toString();
	let cacheKey = jidType + "_" + rowStr;
	if (senderCache.has(cacheKey)) return senderCache.get(cacheKey);

	let phoneNumber = "";

	try {
		let resolvedJidRowId = jidRowId;
		if (jidType === "chat") {
			let cursor = db.rawQuery("SELECT jid_row_id FROM chat WHERE _id = ?", Java.array('java.lang.String', [rowStr]));
			if (cursor && cursor.moveToFirst()) {
				resolvedJidRowId = cursor.getLong(0);
			}
			if (cursor) cursor.close();
		}

		let query = "SELECT raw_string FROM jid WHERE _id = ?";
		let cursor = db.rawQuery(query, Java.array('java.lang.String', [resolvedJidRowId.toString()]));

		let rawJid = "";
		if (cursor && cursor.moveToFirst()) {
			rawJid = cursor.getString(0);
		}
		if (cursor) cursor.close();

		if (rawJid) {
			info.uuid = rawJid;
			phoneNumber = rawJid;
			console.log("[WA Listener] Resolved rawJid: " + rawJid);

			if (rawJid.endsWith("@g.us")) {
				info.type = "group";
			}

			if (rawJid.endsWith("@lid")) {
				console.log("[WA Listener] Attempting to map LID: " + rawJid + " (Row ID: " + resolvedJidRowId + ")");
				cursor = db.rawQuery("SELECT jid_row_id FROM jid_map WHERE lid_row_id = ?", Java.array('java.lang.String', [resolvedJidRowId.toString()]));

				let realJidRowId = -1;
				if (cursor && cursor.moveToFirst()) {
					realJidRowId = cursor.getLong(0);
				}
				if (cursor) cursor.close();

				if (realJidRowId !== -1) {
					cursor = db.rawQuery("SELECT raw_string FROM jid WHERE _id = ?", Java.array('java.lang.String', [realJidRowId.toString()]));
					if (cursor && cursor.moveToFirst()) {
						let realJid = cursor.getString(0);
						if (realJid) {
							phoneNumber = realJid;
						}
					}
					if (cursor) cursor.close();
				}
			}
		}

		if (phoneNumber && phoneNumber !== "") {
			let justNumber = phoneNumber;
			if (phoneNumber.indexOf("@s.whatsapp.net") !== -1) {
				justNumber = phoneNumber.split("@")[0];
			}
			info.phone = justNumber;
		}

		try {
			let currentPath = db.getPath();
			if (currentPath.endsWith("msgstore.db")) {
				let waPath = currentPath.replace("msgstore.db", "wa.db");
				let SQLiteDatabase = Java.use("android.database.sqlite.SQLiteDatabase");
				let waDb = SQLiteDatabase.openDatabase(waPath, null, 1);

				if (waDb) {
					let params = [info.uuid];
					let contactCursor = waDb.rawQuery("SELECT wa_name, display_name FROM wa_contacts WHERE jid = ?", Java.array('java.lang.String', params));

					if (contactCursor && contactCursor.moveToFirst()) {
						let waName = contactCursor.getString(0);
						let displayName = contactCursor.getString(1);
						info.username = waName || displayName || "";
					}
					if (contactCursor) contactCursor.close();
					waDb.close();
				}
			}
		} catch (dbErr) { }

	} catch (e) {
		console.error("[resolveJidInfo] Error: " + e);
	}

	senderCache.set(cacheKey, info);
	return info;
}

export function init(db, initialValues) {
	const Base64 = Java.use("android.util.Base64");
	try {
		let messageType = initialValues.getAsInteger("message_type");
		let content = initialValues.getAsString("text_data");
		let mediaUrl = initialValues.getAsString("media_url");
		let mediaType = initialValues.getAsString("media_type");

		// Text message (type 0 or null)
		if (content && (messageType === null || messageType.intValue() === 0)) {
			let fromMe = initialValues.getAsInteger("from_me");
			let timestamp = initialValues.getAsLong("timestamp");
			let chatRowId = initialValues.getAsLong("chat_row_id");
			let senderJidRowId = initialValues.getAsLong("sender_jid_row_id");

			let type = (fromMe && fromMe.intValue() === 1) ? "OUTGOING" : "INCOMING";
			let dateStr = new Date(timestamp ? timestamp.longValue() : Date.now()).toLocaleString();

			let chatInfo = resolveJidInfo(db, chatRowId, "chat");

			let senderInfo = chatInfo;
			if (senderJidRowId && senderJidRowId.longValue() !== -1 && senderJidRowId.longValue() !== 0) {
				console.log("[WA Listener] Resolving Sender JID Row: " + senderJidRowId.toString());
				let explicitSender = resolveJidInfo(db, senderJidRowId, "person");
				if (explicitSender && explicitSender.uuid) {
					senderInfo = explicitSender;
				} else {
					console.log("[WA Listener] Failed to resolve sender info for row " + senderJidRowId + ", falling back to chat info.");
				}
			} else {
				console.log("[WA Listener] No valid sender_jid_row_id (" + senderJidRowId + "), using chat info.");
			}

			let javaString = Java.use("java.lang.String").$new(content.toString());
			let encodedContent = Base64.encodeToString(javaString.getBytes("UTF-8"), 2);

			return {
				type: type,
				is_group: chatInfo.type === "group",
				chat: {
					uuid: chatInfo.uuid,
					name: chatInfo.username,
					type: chatInfo.type
				},
				user_info: {
					uuid: senderInfo.uuid,
					username: senderInfo.username,
					phone: senderInfo.phone
				},
				content: encodedContent,
				time: dateStr,
			};
		}

		// Image message (type 1 = image, or has media_url with image type)
		let isImageMessage = (messageType && messageType.intValue() === 1) || 
			(mediaUrl && mediaUrl.length > 0 && (!mediaType || mediaType.startsWith("image")));
		
		if (isImageMessage && mediaUrl && mediaUrl.length > 0) {
			let fromMe = initialValues.getAsInteger("from_me");
			let timestamp = initialValues.getAsLong("timestamp");
			let chatRowId = initialValues.getAsLong("chat_row_id");
			let senderJidRowId = initialValues.getAsLong("sender_jid_row_id");

			let type = (fromMe && fromMe.intValue() === 1) ? "OUTGOING" : "INCOMING";
			let dateStr = new Date(timestamp ? timestamp.longValue() : Date.now()).toLocaleString();

			let chatInfo = resolveJidInfo(db, chatRowId, "chat");

			let senderInfo = chatInfo;
			if (senderJidRowId && senderJidRowId.longValue() !== -1 && senderJidRowId.longValue() !== 0) {
				console.log("[WA Listener] Resolving Sender JID Row: " + senderJidRowId.toString());
				let explicitSender = resolveJidInfo(db, senderJidRowId, "person");
				if (explicitSender && explicitSender.uuid) {
					senderInfo = explicitSender;
				} else {
					console.log("[WA Listener] Failed to resolve sender info for row " + senderJidRowId + ", falling back to chat info.");
				}
			} else {
				console.log("[WA Listener] No valid sender_jid_row_id (" + senderJidRowId + "), using chat info.");
			}

			// Encode media URL as content (processor will use it for image reply)
			let javaString = Java.use("java.lang.String").$new(mediaUrl.toString());
			let encodedContent = Base64.encodeToString(javaString.getBytes("UTF-8"), 2);

			let caption = initialValues.getAsString("caption") || "";
			let encodedCaption = caption ? Base64.encodeToString(
				Java.use("java.lang.String").$new(caption).getBytes("UTF-8"), 2
			) : "";

			console.log("[WA Listener] Image message detected: " + mediaUrl);

			return {
				type: type,
				is_group: chatInfo.type === "group",
				chat: {
					uuid: chatInfo.uuid,
					name: chatInfo.username,
					type: chatInfo.type
				},
				user_info: {
					uuid: senderInfo.uuid,
					username: senderInfo.username,
					phone: senderInfo.phone
				},
				content: encodedContent,
				caption: encodedCaption,
				media_type: "image",
				media_url: mediaUrl,
				time: dateStr,
			};
		}
	} catch (e) {
		console.error("[wa_message_listener] Error: " + e);
	}
	return null;
}
