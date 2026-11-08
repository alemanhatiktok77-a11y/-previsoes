package com.previsoes.jogos;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends Activity {
    private WebView web;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.parseColor("#0e1116"));
        getWindow().setNavigationBarColor(Color.parseColor("#0e1116"));
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0e1116"));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        web.setWebViewClient(new WebViewClient());
        web.addJavascriptInterface(new Net(), "AndroidNet");
        setContentView(web);
        web.loadUrl("file:///android_asset/index.html");
    }

    /** Faz as requisições de internet pelo Android (sem bloqueio de CORS). */
    class Net {
        @JavascriptInterface
        public void get(final String id, final String url) {
            new Thread(() -> {
                String body = "", err = "";
                try {
                    HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
                    c.setConnectTimeout(15000);
                    c.setReadTimeout(20000);
                    c.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36");
                    int code = c.getResponseCode();
                    InputStream in = code < 400 ? c.getInputStream() : c.getErrorStream();
                    if (in != null) {
                        ByteArrayOutputStream out = new ByteArrayOutputStream();
                        byte[] buf = new byte[8192];
                        int n;
                        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                        in.close();
                        body = out.toString("UTF-8");
                    }
                    if (code >= 400) err = "HTTP " + code;
                    c.disconnect();
                } catch (Exception e) {
                    err = e.getClass().getSimpleName() + ": " + e.getMessage();
                }
                final String js = "window.__netCb(" + JSONObject.quote(id) + "," + JSONObject.quote(body) + ","
                        + JSONObject.quote(err) + ")";
                web.post(() -> web.evaluateJavascript(js, null));
            }).start();
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
