package br.cacau.radar;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;

import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/**
 * A cada 6 horas consulta a API do Radar e avisa, com notificação, o que é novo:
 * eventos literários em Sergipe (sergipe.json) e lançamentos dos autores acompanhados (alertas.json).
 * Na primeira vez só memoriza o que já existe e manda um aviso de que está funcionando.
 */
public class AvisosWorker extends Worker {

    private static final String CANAL = "avisos";
    private static final int MAX_NOTIFICACOES = 5;

    public AvisosWorker(@NonNull Context ctx, @NonNull WorkerParameters params) {
        super(ctx, params);
    }

    static void agendar(Context ctx) {
        Constraints rede = new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
        WorkManager wm = WorkManager.getInstance(ctx);
        wm.enqueueUniquePeriodicWork("avisos", ExistingPeriodicWorkPolicy.KEEP,
                new PeriodicWorkRequest.Builder(AvisosWorker.class, 6, TimeUnit.HOURS).setConstraints(rede).build());
        wm.enqueueUniqueWork("avisos-agora", ExistingWorkPolicy.KEEP,
                new OneTimeWorkRequest.Builder(AvisosWorker.class).setConstraints(rede).build());
    }

    private static final class Aviso {
        final String id, titulo, texto, secao;
        Aviso(String id, String titulo, String texto, String secao) {
            this.id = id; this.titulo = titulo; this.texto = texto; this.secao = secao;
        }
    }

    @NonNull
    @Override
    public Result doWork() {
        Context ctx = getApplicationContext();
        SharedPreferences prefs = ctx.getSharedPreferences("avisos", Context.MODE_PRIVATE);
        Set<String> vistos = new HashSet<>(prefs.getStringSet("vistos", new HashSet<>()));
        boolean primeira = !prefs.getBoolean("iniciado", false);
        try {
            List<Aviso> todos = new ArrayList<>();
            JSONArray eventos = new JSONObject(baixar(MainActivity.SITE + "api/sergipe.json")).optJSONArray("eventos");
            for (int k = 0; eventos != null && k < eventos.length(); k++) {
                JSONObject e = eventos.getJSONObject(k);
                todos.add(new Aviso("s-" + e.optString("id"), "📍 Evento literário em Sergipe",
                        e.optString("titulo"), "sergipe"));
            }
            JSONArray alertas = new JSONObject(baixar(MainActivity.SITE + "api/alertas.json")).optJSONArray("alertas");
            for (int k = 0; alertas != null && k < alertas.length(); k++) {
                JSONObject a = alertas.getJSONObject(k);
                JSONArray autores = a.optJSONArray("autores");
                String quem = autores != null && autores.length() > 0 ? autores.optString(0) : "Autor que você acompanha";
                todos.add(new Aviso("a-" + a.optString("id"), "📚 " + quem, a.optString("titulo"), "estante"));
            }

            Set<String> atuais = new HashSet<>();
            List<Aviso> novos = new ArrayList<>();
            for (Aviso av : todos) {
                atuais.add(av.id);
                if (!vistos.contains(av.id)) novos.add(av);
            }

            if (primeira) {
                int n = 0;
                for (Aviso av : todos) if (av.secao.equals("sergipe")) n++;
                notificar(ctx, 1, "Radar Literário ativo",
                        "Você vai ser avisado de cada evento literário em Sergipe e dos lançamentos dos seus autores. "
                                + (n > 0 ? "Agora há " + n + " no radar." : ""), "sergipe");
            } else if (novos.size() > MAX_NOTIFICACOES) {
                notificar(ctx, 2, "Radar Literário", novos.size() + " novidades: eventos em Sergipe e lançamentos.", "sergipe");
            } else {
                for (Aviso av : novos) notificar(ctx, av.id.hashCode(), av.titulo, av.texto, av.secao);
            }

            // Guarda só o que ainda está nas listas: o que saiu delas não volta.
            prefs.edit().putStringSet("vistos", atuais).putBoolean("iniciado", true).apply();
            return Result.success();
        } catch (Exception e) {
            return Result.retry();
        }
    }

    private static String baixar(String endereco) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(endereco).openConnection();
        c.setConnectTimeout(20000);
        c.setReadTimeout(20000);
        c.setUseCaches(false);
        try (InputStream in = c.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString(StandardCharsets.UTF_8.name());
        } finally {
            c.disconnect();
        }
    }

    private static void notificar(Context ctx, int id, String titulo, String texto, String secao) {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            return;
        }
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel canal = new NotificationChannel(CANAL, ctx.getString(R.string.canal_nome),
                    NotificationManager.IMPORTANCE_DEFAULT);
            canal.setDescription(ctx.getString(R.string.canal_descricao));
            ctx.getSystemService(NotificationManager.class).createNotificationChannel(canal);
        }
        Intent abrir = new Intent(ctx, MainActivity.class)
                .putExtra(MainActivity.EXTRA_SECAO, secao)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent toque = PendingIntent.getActivity(ctx, id, abrir,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder n = new NotificationCompat.Builder(ctx, CANAL)
                .setSmallIcon(R.drawable.ic_aviso)
                .setColor(0xFF66577D)
                .setContentTitle(titulo)
                .setContentText(texto)
                .setStyle(new NotificationCompat.BigTextStyle().bigText(texto))
                .setContentIntent(toque)
                .setAutoCancel(true);
        try {
            NotificationManagerCompat.from(ctx).notify(id, n.build());
        } catch (SecurityException ignorada) {
            // permissão retirada no meio do caminho: fica sem notificar
        }
    }
}
