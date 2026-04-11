using System;
using System.Net.Http;
using System.Text;
using System.Text.RegularExpressions;

public class CPHInline
{
    public bool Execute()
    {
        string orchestratorUrl = "http://127.0.0.1:8000";
        string botMention = "@robokot_bot";
        string botUserName = "robokot_bot";
        string streamId = "main-stream";

        CPH.TryGetArg("userName", out string userName);
        CPH.TryGetArg("message", out string message);
        CPH.TryGetArg("msgId", out string msgId);

        CPH.TryGetArg("reply.msgId", out string replyMsgId);
        CPH.TryGetArg("reply.userLogin", out string replyUserLogin);
        CPH.TryGetArg("reply.userName", out string replyUserName);
        CPH.TryGetArg("reply.msgBody", out string replyMsgBody);

        if (string.IsNullOrWhiteSpace(userName) || string.IsNullOrWhiteSpace(message))
            return true;

        // защита от цикла: не реагировать на собственные сообщения бота
        if (string.Equals(userName, botUserName, StringComparison.OrdinalIgnoreCase))
        {
            CPH.LogInfo("DEBUG: ignore own bot message");
            return true;
        }

        if (message.IndexOf(botMention, StringComparison.OrdinalIgnoreCase) < 0)
            return true;

        string replyToUsername = !string.IsNullOrWhiteSpace(replyUserName) ? replyUserName : replyUserLogin;
        string replyToText = DecodeReplyBody(replyMsgBody);

        string payload =
            "{"
            + "\"stream_id\":\"" + EscapeJson(streamId) + "\","
            + "\"username\":\"" + EscapeJson(userName) + "\","
            + "\"text\":\"" + EscapeJson(message) + "\","
            + "\"mentions_bot\":true,"
            + "\"role\":\"viewer\","
            + "\"message_id\":\"" + EscapeJson(msgId) + "\","
            + "\"reply_to_message_id\":\"" + EscapeJson(replyMsgId) + "\","
            + "\"reply_to_username\":\"" + EscapeJson(replyToUsername) + "\","
            + "\"reply_to_text\":\"" + EscapeJson(replyToText) + "\""
            + "}";

        try
        {
            using (var client = new HttpClient())
            {
                client.Timeout = TimeSpan.FromSeconds(20);

                using (var content = new StringContent(payload, Encoding.UTF8, "application/json"))
                {
                    var response = client.PostAsync(orchestratorUrl + "/events/chat_reply", content)
                        .GetAwaiter()
                        .GetResult();

                    string responseBody = response.Content.ReadAsStringAsync()
                        .GetAwaiter()
                        .GetResult();

                    CPH.LogInfo("AI reply status: " + ((int)response.StatusCode).ToString());
                    CPH.LogInfo("AI reply body: " + responseBody);
                    CPH.LogInfo("Twitch msgId: " + (msgId ?? "<null>"));
                    CPH.LogInfo("reply.msgId: " + (replyMsgId ?? "<null>"));
                    CPH.LogInfo("reply.user: " + (replyToUsername ?? "<null>"));
                    CPH.LogInfo("reply.text: " + (replyToText ?? "<null>"));

                    if (!response.IsSuccessStatusCode)
                        return true;

                    bool shouldReply = ExtractBool(responseBody, "should_reply");
                    string replyText = ExtractString(responseBody, "reply_text");

                    if (!shouldReply || string.IsNullOrWhiteSpace(replyText))
                        return true;

                    // reply к сообщению пользователя
                    if (!string.IsNullOrWhiteSpace(msgId))
                    {
                        CPH.TwitchReplyToMessage(replyText, msgId, true, true);
                    }
                    else
                    {
                        CPH.SendMessage(replyText, true, true);
                    }

                    string botPayload =
                        "{"
                        + "\"stream_id\":\"" + EscapeJson(streamId) + "\","
                        + "\"username\":\"" + EscapeJson(botUserName) + "\","
                        + "\"text\":\"" + EscapeJson(replyText) + "\","
                        + "\"mentions_bot\":false,"
                        + "\"role\":\"bot\""
                        + "}";

                    using (var botContent = new StringContent(botPayload, Encoding.UTF8, "application/json"))
                    {
                        var botResponse = client.PostAsync(orchestratorUrl + "/events/chat_ingest", botContent)
                            .GetAwaiter()
                            .GetResult();

                        CPH.LogInfo("AI bot-ingest status: " + ((int)botResponse.StatusCode).ToString());
                    }
                }
            }
        }
        catch (Exception ex)
        {
            CPH.LogError("AI reply action failed: " + ex.ToString());
        }

        return true;
    }

    private string DecodeReplyBody(string value)
    {
        if (string.IsNullOrEmpty(value))
            return "";

        return value
            .Replace("\\s", " ")
            .Replace("\\n", "\n")
            .Replace("\\r", "\r")
            .Replace("\\t", "\t");
    }

    private string EscapeJson(string value)
    {
        if (value == null)
            return "";

        return value
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\r", "\\r")
            .Replace("\n", "\\n")
            .Replace("\t", "\\t");
    }

    private bool ExtractBool(string json, string fieldName)
    {
        string pattern = "\"" + Regex.Escape(fieldName) + "\"\\s*:\\s*(true|false)";
        Match match = Regex.Match(json, pattern, RegexOptions.IgnoreCase);

        if (!match.Success)
            return false;

        return string.Equals(match.Groups[1].Value, "true", StringComparison.OrdinalIgnoreCase);
    }

    private string ExtractString(string json, string fieldName)
    {
        string pattern = "\"" + Regex.Escape(fieldName) + "\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"";
        Match match = Regex.Match(json, pattern, RegexOptions.Singleline);

        if (!match.Success)
            return "";

        string value = match.Groups[1].Value;

        value = value.Replace("\\n", "\n");
        value = value.Replace("\\r", "\r");
        value = value.Replace("\\t", "\t");
        value = value.Replace("\\\"", "\"");
        value = value.Replace("\\\\", "\\");

        return value;
    }
}