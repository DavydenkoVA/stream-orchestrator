using System;
using System.Net.Http;
using System.Text;
using System.Text.RegularExpressions;

public class CPHInline
{
    public bool Execute()
    {
        CPH.TryGetArg("userName", out string userName);
        CPH.TryGetArg("rawInput", out string message);
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
            CPH.LogInfo("DEBUG: no bot mention");
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

                using (var content = new StringContent(payload, Encoding.UTF8, "application/json"))
                {
                    var response = client.PostAsync(orchestratorUrl + "/events/chat_reply", content)
                        .GetAwaiter()
                        .GetResult();

                    string responseBody = response.Content.ReadAsStringAsync()
                        .GetAwaiter()
                        .GetResult();

                    CPH.LogInfo("AI reply status: " + ((int)response.StatusCode));
                    CPH.LogInfo("AI reply body: " + responseBody);

                    if (!response.IsSuccessStatusCode)
                        return true;

                    bool shouldReply = ExtractBool(responseBody, "should_reply");
                    string replyText = ExtractString(responseBody, "reply_text");

                    if (!shouldReply || string.IsNullOrWhiteSpace(replyText))
                        return true;

                    if (!string.IsNullOrWhiteSpace(msgId))
                    {
                        CPH.SetArgument("replyMessageId", msgId);
                    }

                    CPH.SendMessage(replyText, true, true);

                    // логируем ответ бота обратно в оркестратор
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
                        client.PostAsync(orchestratorUrl + "/events/chat_ingest", botContent)
                            .GetAwaiter()
                            .GetResult();
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
        return match.Success && match.Groups[1].Value.ToLower() == "true";
    }

    private string ExtractString(string json, string fieldName)
    {
        string pattern = "\"" + Regex.Escape(fieldName) + "\"\\s*:\\s*\"((?:\\\\.|[^\"])*)\"";
        Match match = Regex.Match(json, pattern, RegexOptions.Singleline);

        if (!match.Success)
            return "";

        string value = match.Groups[1].Value;

        return value
            .Replace("\\n", "\n")
            .Replace("\\r", "\r")
            .Replace("\\t", "\t")
            .Replace("\\\"", "\"")
            .Replace("\\\\", "\\");
    }
}