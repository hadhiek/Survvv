/* Copy into the response spreadsheet's Apps Script project, edit CONFIG, then
 * create an installable trigger: onFormSubmit → From spreadsheet → On form submit.
 */
const CONFIG = {
  surveyId: 123,
  formId: "GOOGLE_FORM_ID",
  webhookUrl: "https://your-api.example.com/webhooks/google-form",
  webhookSecret: "COPY_THE_ONE_TIME_SECRET_FROM_SURVEY_CREATION",
  participationCodeColumn: "Participation Code"
};
function onFormSubmit(e) {
  const code = e.namedValues[CONFIG.participationCodeColumn]?.[0];
  if (!code) throw new Error("Missing required Participation Code column");
  const payload = {survey_id: CONFIG.surveyId, form_id: CONFIG.formId, participation_token: code, webhook_secret: CONFIG.webhookSecret, submitted_at: new Date().toISOString()};
  const result = UrlFetchApp.fetch(CONFIG.webhookUrl, {method:"post",contentType:"application/json",payload:JSON.stringify(payload),muteHttpExceptions:true});
  if (result.getResponseCode() >= 300) throw new Error("Webhook failed: " + result.getContentText());
}
