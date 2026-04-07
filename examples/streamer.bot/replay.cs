using System;
using System.Net.Http;
using System.Text;
using System.Text.RegularExpressions;

public class CPHInline
{
    public bool Execute()
    {
        CPH.TryGetArg("userName", out string userName);
        CPH.TryGetArg("message", out string message);
        CPH.TryGetArg("reply.threadMsgId", out string msgId);

        if (string.IsNullOrWhiteSpace(userName) || string.IsNullOrWhiteSpace(message))
        {
            CPH.LogInfo("DEBUG: empty userName or message");
            return true;
        }

        string orchestratorUrl = "http://127.0.0.1:8000";
        string botMention = "@robokot_bot";
        string botUserName = "robokot_bot";
        string streamId = "main-stream";

        if (message.IndexOf(botMention, StringComparison.OrdinalIgnoreCase) < 0)
        {
            return true;
        }

        string payload =
            "{"
            + "\"stream_id\":\"" + EscapeJson(streamId) + "\","
            + "\"username\":\"" + EscapeJson(userName) + "\","
            + "\"text\":\"" + EscapeJson(message) + "\","
            + "\"mentions_bot\":true,"
            + "\"role\":\"viewer\""
            + "}";

        try
        {
            using (var client = new HttpClient())
            {
                client.Timeout = TimeSpan.FromSeconds(20);

                var response = client.PostAsync(
                    orchestratorUrl + "/events/chat_reply",
                    new StringContent(payload, Encoding.UTF8, "application/json")
                ).GetAwaiter().GetResult();

                string body = response.Content.ReadAsStringAsync()
                    .GetAwaiter()
                    .GetResult();

                CPH.LogInfo("AI status: " + ((int)response.StatusCode));
                CPH.LogInfo("AI body: " + body);

                if (!response.IsSuccessStatusCode)
                    return true;

                bool shouldReply = ExtractBool(body, "should_reply");
                string replyText = ExtractString(body, "reply_text");

                if (!shouldReply || string.IsNullOrWhiteSpace(replyText))
                    return true;

                // reply в тред
                if (!string.IsNullOrWhiteSpace(msgId))
                {
                    CPH.SetArgument("replyMessageId", msgId);
                }

                CPH.SendMessage(replyText, true, true);

                // лог бота обратно
                string botPayload =
                    "{"
                    + "\"stream_id\":\"" + EscapeJson(streamId) + "\","
                    + "\"username\":\"" + EscapeJson(botUserName) + "\","
                    + "\"text\":\"" + EscapeJson(replyText) + "\","
                    + "\"mentions_bot\":false,"
                    + "\"role\":\"bot\""
                    + "}";

                client.PostAsync(
                    orchestratorUrl + "/events/chat_ingest",
                    new StringContent(botPayload, Encoding.UTF8, "application/json")
                ).GetAwaiter().GetResult();
            }
        }
        catch (Exception ex)
        {
            CPH.LogError("AI failed: " + ex.ToString());
        }

        return true;
    }

    private string EscapeJson(string value)
    {
        if (value == null) return "";

        return value
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\r", "\\r")
            .Replace("\n", "\\n");
    }

    private bool ExtractBool(string json, string field)
    {
        var m = Regex.Match(json, $"\"{field}\"\\s*:\\s*(true|false)", RegexOptions.IgnoreCase);
        return m.Success && m.Groups[1].Value.ToLower() == "true";
    }

    private string ExtractString(string json, string field)
    {
        var m = Regex.Match(json, $"\"{field}\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"", RegexOptions.Singleline);
        if (!m.Success) return "";

        return m.Groups[1].Value
            .Replace("\\n", "\n")
            .Replace("\\\"", "\"")
            .Replace("\\\\", "\\");
    }
}