import Java from "frida-java-bridge";

export function init(db, table, initialValues) {
	const Base64 = Java.use("android.util.Base64");
	try {
		if (table !== "chat_history") return null;

		let type = initialValues.getAsInteger("type");

		if (type && type.intValue() == 1) {
			let content = initialValues.getAsString("content");
			let createdTime = initialValues.getAsLong("created_time");
			let fromMid = initialValues.getAsString("from_mid");

			let dateStr = new Date(createdTime ? createdTime.longValue() : Date.now()).toLocaleString();

			let direction = (fromMid && fromMid !== "0" && fromMid !== "") ? 'INCOMING' : 'OUTGOING';

			// Encode content as Base64 (same as WhatsApp listener)
			let encodedContent = content;
			if (content) {
				let javaString = Java.use("java.lang.String").$new(content.toString());
				encodedContent = Base64.encodeToString(javaString.getBytes("UTF-8"), 2);
			}

			let result = {
				type: direction,
				user_info: {
					uuid: fromMid || "",
					username: "",
					phone: ""
				},
				time: dateStr,
				content: encodedContent,
			};

			if (fromMid && fromMid !== "0") {

				// 1. Contact DB (Friends/Synced Contacts)
				let contactDb = null;
				try {
					const SQLiteDatabase = Java.use("android.database.sqlite.SQLiteDatabase");
					const contactDbPath = "/data/user/0/jp.naver.line.android/databases/contact";
					const File = Java.use("java.io.File");
					const dbFile = File.$new(contactDbPath);

					if (dbFile.exists()) {
						contactDb = SQLiteDatabase.openDatabase(contactDbPath, null, 1);
						if (contactDb) {
							let cursor = contactDb.rawQuery(
								"SELECT profile_name, overridden_name FROM contacts WHERE mid = ? LIMIT 1",
								Java.array('java.lang.String', [fromMid])
							);

							if (cursor && cursor.moveToFirst()) {
								let profileName = cursor.getString(0);

								if (profileName) result.user_info.username = profileName;

								cursor.close();
							} else {
								if (cursor) cursor.close();
							}
						}
					}
				} catch (e) {
					// console.log("[Line Contact DB Error] " + e);
				} finally {
					if (contactDb) try { contactDb.close(); } catch (e) { }
				}

				// 2. Membership Check (Main DB - Group Members)
				if (result.user_info.username === "Unknown") {
					try {
						let memCursor = db.rawQuery(
							"SELECT display_name FROM membership WHERE mid = ? LIMIT 1",
							Java.array('java.lang.String', [fromMid])
						);
						if (memCursor && memCursor.moveToFirst()) {
							let dName = memCursor.getString(0);
							if (dName) {
								if (result.user_info.username === "Unknown") {
									result.user_info.username = dName;
								}
							}
							memCursor.close();
						} else {
							if (memCursor) memCursor.close();
						}
					} catch (e) { }
				}

				// 3. Fallback Phone Check (Main DB - normalized_phone is rare but standard)
				try {
					let phoneCursor = db.rawQuery(
						"SELECT normalized_phone FROM normalized_phone WHERE mid = ? LIMIT 1",
						Java.array('java.lang.String', [fromMid])
					);

					if (phoneCursor && phoneCursor.moveToFirst()) {
						let phone = phoneCursor.getString(0);
						if (phone) {
							result.user_info.phone = phone;
						}
						phoneCursor.close();
					} else {
						if (phoneCursor) phoneCursor.close();
					}
				} catch (e) { }
			}

			return result;
		}
	} catch (e) {
		console.error("[line_message_listener] Error: " + e);
	}
	return null;
}