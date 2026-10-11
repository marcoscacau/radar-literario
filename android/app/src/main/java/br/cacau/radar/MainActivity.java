package br.cacau.radar;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

/** O app é o próprio Radar (a página publicada no GitHub Pages) dentro de uma janela, com puxar-para-atualizar. */
public class MainActivity extends Activity {

    static final String SITE = "https://marcoscacau.github.io/radar-literario/";
    static final String EXTRA_SECAO = "secao";

    private WebView web;
    private SwipeRefreshLayout puxar;
    private boolean tentouCache = false;

    @Override
    protected void onCreate(Bundle salvo) {
        super.onCreate(salvo);
        web = new WebView(this);
        puxar = new SwipeRefreshLayout(this);
        puxar.addView(web);
        puxar.setColorSchemeColors(Color.parseColor("#66577D"));
        puxar.setProgressBackgroundColorSchemeColor(Color.parseColor("#E8E0F0"));
        // Só atualiza puxando quando a página está no topo.
        puxar.setOnChildScrollUpCallback((pai, filho) -> web.getScrollY() > 0);
        puxar.setOnRefreshListener(() -> {
            tentouCache = false;
            web.getSettings().setCacheMode(WebSettings.LOAD_DEFAULT);
            web.reload();
        });
        setContentView(puxar);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);          // seção escolhida, Edição antiga e "aprendendo com você"
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setUserAgentString(s.getUserAgentString() + " RadarLiterarioApp/" + BuildConfigVersao.nome(this));

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest pedido) {
                Uri u = pedido.getUrl();
                if (doRadar(u)) return false;
                try {   // notícia: abre no navegador do celular
                    startActivity(new Intent(Intent.ACTION_VIEW, u));
                } catch (Exception e) {
                    Toast.makeText(MainActivity.this, "Não consegui abrir o link.", Toast.LENGTH_SHORT).show();
                }
                return true;
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                puxar.setRefreshing(false);
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest pedido, WebResourceError erro) {
                if (!pedido.isForMainFrame()) return;
                puxar.setRefreshing(false);
                if (!tentouCache) {            // sem internet: tenta a última versão guardada
                    tentouCache = true;
                    v.getSettings().setCacheMode(WebSettings.LOAD_CACHE_ELSE_NETWORK);
                    v.reload();
                } else {
                    Toast.makeText(MainActivity.this, R.string.sem_internet, Toast.LENGTH_LONG).show();
                }
            }
        });

        if (salvo != null) {
            web.restoreState(salvo);
        } else {
            web.loadUrl(endereco(getIntent()));
        }

        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
        AvisosWorker.agendar(this);
    }

    static boolean doRadar(Uri u) {
        return "marcoscacau.github.io".equals(u.getHost())
                && u.getPath() != null && u.getPath().startsWith("/radar-literario");
    }

    private static String endereco(Intent intent) {
        String secao = intent == null ? null : intent.getStringExtra(EXTRA_SECAO);
        return secao == null ? SITE : SITE + "?secao=" + Uri.encode(secao);
    }

    @Override
    protected void onNewIntent(Intent intent) {   // toque numa notificação com o app aberto
        super.onNewIntent(intent);
        if (intent.getStringExtra(EXTRA_SECAO) != null) web.loadUrl(endereco(intent));
    }

    @Override
    protected void onSaveInstanceState(Bundle estado) {
        super.onSaveInstanceState(estado);
        web.saveState(estado);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
