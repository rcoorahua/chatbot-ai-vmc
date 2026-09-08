import type { CSSProperties } from "react";
import type { Message } from "@/lib/types";
import { formatTimestamp, linkify, SYSTEM_EVENT_LABEL } from "@/lib/format";
import { ImageIcon } from "@/components/icons";

/**
 * Mismo look que el widget (`widget/src/13-styles.js`, `.bubble-mine`): degradado plano
 * vault-500 → vault-700 en 150deg, sin borde. Los tokens tienen el mismo valor en los dos
 * lados (`globals.css` y el `:host` del widget), asi que el asesor ve el hilo con los colores
 * con los que el usuario lo vio.
 *
 * Antes esto portaba el boton `secondary` de Concorde (doble degradado con borde lila y
 * text-shadow) y habia que mantenerlo en sync con ese boton; el degradado del widget es la
 * referencia correcta para una burbuja y no arrastra esa dependencia.
 */
const OURS_BUBBLE_STYLE: CSSProperties = {
  backgroundImage:
    "linear-gradient(150deg, var(--vmc-color-vault-500, #8460e5) 0%, var(--vmc-color-vault-700, #3b1782) 100%)",
  boxShadow: "rgba(32,0,104,0.16) 0 2px 8px",
};

/**
 * RF-034/036: texto con enlaces clicables + timestamp por mensaje. RF-039 excluye a propósito
 * edición/borrado, búsqueda y "escribiendo" — no agregar esas afordancias aquí.
 */
export default function MessageBubble({
  message,
  senderLabel,
}: {
  message: Message;
  /** Nombre a mostrar sobre la burbuja — solo cuando cambia de remitente vs. el mensaje anterior. */
  senderLabel?: string;
}) {
  if (message.message_type === "SYSTEM") {
    const label = SYSTEM_EVENT_LABEL[message.content ?? ""] ?? message.content;
    return (
      <div className="my-2 flex justify-center">
        <span className="rounded-full bg-neutral-200 px-3 py-1 text-xs font-medium text-neutral-600">
          {label}
        </span>
      </div>
    );
  }

  // Quien lee esto es el ASESOR: a la derecha va su lado de la conversacion (lo que el
  // escribio y lo que Subastin respondio por el), a la izquierda el usuario. Antes el bot caia
  // a la izquierda junto al usuario y el hilo se leia como si Subastin fuera el cliente.
  //
  // Los dos lados usan los colores del widget: derecha en vault, izquierda gris con borde. Bot
  // y asesor comparten burbuja a proposito — son el mismo lado de la conversacion; quien
  // hablo lo dice la etiqueta de arriba, que solo sale cuando cambia el remitente.
  const isOurs = message.sender_type === "ADVISOR" || message.sender_type === "BOT";
  const bubbleColor = isOurs
    ? "text-white"
    : "border border-[#ececf3] bg-[#f7f7fb] text-[#191C1C]";
  const align = isOurs ? "items-end" : "items-start";

  return (
    <div className={`flex flex-col ${align} gap-1`}>
      {senderLabel && <span className="px-1 text-xs font-semibold text-neutral-500">{senderLabel}</span>}
      {message.message_type === "IMAGE" ? (
        <div className="flex h-28 w-40 flex-col items-center justify-center gap-1 rounded-2xl border border-neutral-200 bg-neutral-50 text-neutral-400">
          <ImageIcon width={22} height={22} />
          <span className="text-xs">Imagen adjunta</span>
        </div>
      ) : (
        <div
          className={`max-w-md rounded-2xl px-4 py-2.5 ${bubbleColor}`}
          style={isOurs ? OURS_BUBBLE_STYLE : undefined}
        >
          <p className="whitespace-pre-wrap text-sm">
            {linkify(message.content ?? "").map((part, i) =>
              part.href ? (
                <a
                  key={i}
                  href={part.href}
                  target="_blank"
                  rel="noreferrer"
                  className="underline decoration-current"
                >
                  {part.text}
                </a>
              ) : (
                <span key={i}>{part.text}</span>
              ),
            )}
          </p>
        </div>
      )}
      <span className="px-1 text-[11px] text-neutral-500">{formatTimestamp(message.created_at)}</span>
    </div>
  );
}
