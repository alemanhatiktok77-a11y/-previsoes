package com.tvlivre.app;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.GZIPInputStream;

/**
 * Tela principal: interface em HTML (assets/index.html) dentro de um WebView.
 * O download das listas M3U é feito em Java (sem as restrições de CORS do WebView)
 * e a reprodução é feita pelo PlayerActivity (ExoPlayer).
 */
public class MainActivity extends Activity {
    static final String UA = "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36";
    private static final int FILE_REQ = 7;
    private WebView web;
    private ValueCallback<Uri[]> fileCallback;
    private final ExecutorService pool = Executors.newFixedThreadPool(3);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        web.setBackgroundColor(0xFF0B0F17);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(true);
        web.setFocusable(true);
        web.setFocusableInTouchMode(true);
        web.setWebViewClient(new WebViewClient());
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                fileCallback = callback;
                try {
                    Intent i = new Intent(Intent.ACTION_GET_CONTENT);
                    i.addCategory(Intent.CATEGORY_OPENABLE);
                    i.setType("*/*");
                    startActivityForResult(Intent.createChooser(i, "Escolher lista M3U"), FILE_REQ);
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });
        web.addJavascriptInterface(new Bridge(), "Android");
        web.loadUrl("file:///android_asset/index.html");
        web.requestFocus(View.FOCUS_DOWN);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == FILE_REQ && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            fileCallback = null;
        }
    }

    private void realBack() {
        super.onBackPressed();
    }

    @Override
    public void onBackPressed() {
        // a interface decide: fecha uma janela aberta ou sai do app
        web.evaluateJavascript("(window.onBack && window.onBack()) ? 'ok' : 'sair'", value -> {
            if (value == null || !value.contains("ok")) realBack();
        });
    }

    static String download(String address) throws Exception {
        String current = address;
        for (int hop = 0; hop < 6; hop++) {
            HttpURLConnection c = (HttpURLConnection) new URL(current).openConnection();
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(20000);
            c.setReadTimeout(40000);
            c.setRequestProperty("User-Agent", UA);
            c.setRequestProperty("Accept-Encoding", "gzip");
            int code = c.getResponseCode();
            if (code >= 300 && code < 400) {
                String loc = c.getHeaderField("Location");
                c.disconnect();
                if (loc == null) throw new Exception("redirecionamento sem destino");
                current = new URL(new URL(current), loc).toString();   // segue http <-> https
                continue;
            }
            if (code >= 400) throw new Exception("erro HTTP " + code);
            InputStream in = c.getInputStream();
            if ("gzip".equalsIgnoreCase(c.getContentEncoding()) || current.endsWith(".gz")) in = new GZIPInputStream(in);
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[65536];
            int n;
            long total = 0;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
                total += n;
                if (total > 60L * 1024 * 1024) throw new Exception("lista grande demais (mais de 60 MB)");
            }
            in.close();
            c.disconnect();
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
        throw new Exception("redirecionamentos demais");
    }

    /** Funções chamadas pelo JavaScript da interface. */
    class Bridge {
        @JavascriptInterface
        public void fetch(final String url, final String id) {
            pool.execute(() -> {
                boolean ok;
                String res;
                try {
                    res = download(url);
                    ok = true;
                } catch (Exception e) {
                    res = e.getMessage() == null ? e.toString() : e.getMessage();
                    ok = false;
                }
                final String js = "window.onFetch(" + JSONObject.quote(id) + "," + ok + "," + JSONObject.quote(res) + ")";
                runOnUiThread(() -> web.evaluateJavascript(js, null));
            });
        }

        @JavascriptInterface
        public void play(String channelsJson, int index) {
            PlayerActivity.pending = channelsJson;      // lista grande: passada por memória, não pelo Intent
            Intent i = new Intent(MainActivity.this, PlayerActivity.class);
            i.putExtra("index", index);
            startActivity(i);
        }

        @JavascriptInterface
        public boolean isApp() {
            return true;
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.evaluateJavascript("window.onResumeApp && window.onResumeApp()", null);
    }
}
