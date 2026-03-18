import Java from "frida-java-bridge";

const waSendMessage = function (phoneNumber, messageText) {
	return new Promise((resolve, reject) => {
		Java.perform(function () {
			try {
				var ActivityThread = Java.use('android.app.ActivityThread');
				var Uri = Java.use("android.net.Uri");
				var Intent = Java.use("android.content.Intent");

				function getContext() {
					var currentApplication = ActivityThread.currentApplication();
					if (currentApplication == null) return null;
					return currentApplication.getApplicationContext();
				}

				function clickSendButton(attempts) {
					if (!attempts) attempts = 0;
					if (attempts > 20) {
						console.log("   [-] Failed to find Send button after retries.");
						return;
					}

					Java.scheduleOnMainThread(function () {
						var found = false;
						console.log("   [*] Searching UI for Send button... Attempt " + attempts);

						try {
							function checkAndClick(instance) {
								var desc = instance.getContentDescription();
								var resourceName = "";

								try {
									var id = instance.getId();
									if (id !== -1) {
										resourceName = instance.getResources().getResourceEntryName(id);
									}
								} catch (e) {
								}

								if (desc && (desc.toString().toLowerCase() === "send")) {
									if (instance.isShown()) {
										console.log("   [+] Found VISIBLE Send button (by Desc) -> Clicking.");
										instance.performClick();
										found = true;
										return;
									}
								}

								if (resourceName && (resourceName.toString().toLowerCase() === "send")) {
									if (instance.isShown()) {
										console.log("   [+] Found VISIBLE Send button (by ID) -> Clicking.");
										instance.performClick();
										found = true;
										return;
									}
								}
							}

							Java.choose("android.widget.ImageView", {
								onMatch: function (instance) {
									if (!found) checkAndClick(instance);
								},
								onComplete: function () {
									if (!found) {
										Java.choose("android.widget.ImageButton", {
											onMatch: function (instance) {
												if (!found) checkAndClick(instance);
											},
											onComplete: function () {
												if (!found) {
													setTimeout(function () {
														clickSendButton(attempts + 1);
													}, 500);
												}
											}
										});
									}
								}
							});
						} catch (e) {
							console.error("   [-] Error searching UI: " + e);
						}
					});
				}

				Java.scheduleOnMainThread(function () {
					try {
						var context = getContext();
						if (!context) {
							console.error("   [-] Context is null. App not ready.");
							resolve(false);
							return;
						}

						var urlStr = "https://api.whatsapp.com/send?phone=" + phoneNumber + "&text=" + messageText;
						var uri = Uri.parse(urlStr);
						var intent = Intent.$new("android.intent.action.VIEW", uri);
						intent.setFlags(268435456);

						context.startActivity(intent);

						resolve(true);

						setTimeout(function () {
							clickSendButton();
						}, 2500);

					} catch (e) {
						console.error("   [-] Error launching intent: " + e);
						resolve(false);
					}
				});
			} catch (e) {
				console.error("error in sendMessage: " + e);
				resolve(false);
			}
		});
	});
};

globalThis.waSendMessage = waSendMessage;

export function send(phoneNumber, message) {
	return waSendMessage(phoneNumber, message);
}
