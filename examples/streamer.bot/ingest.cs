using System;
using System.Net.Http;
using System.Text;

public class CPHInline
{
    public bool Execute()
    {
        CPH.TryGetArg("userName", out string userName);
        CPH.TryGetArg("message", out string message);

        if (string.IsNullOrWhiteSpace(userName) || string.IsNullOrWhiteSpace(message))
            return true;

        string orchestratorUrl = "http://127.0.0.1:8000";
        string botMention = "@streamer_bot";   // тот же тег
        string streamId = "main-stream";

        if (message.IndexOf(botMention, StringComparison.OrdinalIgnoreCase) >= 0)
            return true;

        string payload =
            "{"
            + "\"stream_id\":\"" + EscapeJson(streamId) + "\","
            + "\"username\":\"" + EscapeJson(userName) + "\","
            + "\"text\":\"" + EscapeJson(message) + "\","
            + "\"mentions_bot\":false,"
            + "\"role\":\"viewer\""
            + "}";

        try
        {
            using (var client = new HttpClient())
            {
                client.Timeout = TimeSpan.FromSeconds(10);

                using (var content = new StringContent(payload, Encoding.UTF8, "application/json"))
                {
                    var response = client.PostAsync(orchestratorUrl + "/events/chat_ingest", content)
                        .GetAwaiter()
                        .GetResult();

                    CPH.LogInfo("AI ingest status: " + ((int)response.StatusCode).ToString());
                }
            }
        }
        catch (Exception ex)
        {
            CPH.LogError("AI ingest action failed: " + ex.ToString());
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
}