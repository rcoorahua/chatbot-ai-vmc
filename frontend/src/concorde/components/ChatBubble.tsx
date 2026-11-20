/**
 * ChatBubble — mensaje del SubasChat (Mi Garaje, mi-garaje-lab · /m/oferta y el chat del panel de negociación):
 * burbuja blanca para la contraparte y violeta (vault-500 → vault-700) para lo tuyo, con la hora abajo y, en lo tuyo,
 * el estado del envío (◷ enviando, ✓✓ enviado, ! no enviado). En una ráfaga (cont / more) se aplanan las esquinas
 * y solo la última lleva la hora. Puede llevar una imagen. Solo depende de React.
 */
import type { JSX, ReactNode } from "react";

export const CHAT_BUBBLE_CSS = String.raw`
.sc__row { display: flex; flex-direction: column; align-items: flex-start; animation: sc-in 0.18s ease-out; }
.sc__row.is-mine { align-items: flex-end; }
.sc__row.is-cont { margin-top: -4px; } /* ráfaga: 2px entre burbujas del mismo emisor (gap 6) */
@keyframes sc-in { from { opacity: 0; transform: translateY(6px); } }
.sc__bubble { max-width: 84%; padding: 8px 12px 6px; border-radius: 16px 16px 16px 4px; color: #191C1C; background: #fff; box-shadow: 0 1px 2px rgba(34, 0, 92, 0.08); transition: opacity 0.2s; }
.is-mine > .sc__bubble { border-radius: 16px 16px 4px 16px; color: #fff; background-image: linear-gradient(150deg, #8460e5 0%, #3b1782 100%); box-shadow: rgba(32, 0, 104, 0.16) 0 2px 8px; }
.is-cont > .sc__bubble { border-top-left-radius: 4px; }
.is-mine.is-cont > .sc__bubble { border-top-left-radius: 16px; border-top-right-radius: 4px; }
.sc__bubble p { margin: 0; font-size: 14px; line-height: 1.4; white-space: pre-wrap; overflow-wrap: anywhere; }
.sc__bubble.has-img { padding: 4px 4px 6px; }
.sc__bubble img { display: block; max-width: 200px; max-height: 180px; border-radius: 12px; }
.sc__bubble.has-img p { padding: 6px 8px 0; }
.sc__bubble.is-sending .sc__tick { opacity: 0.7; }
.sc__bubble.is-failed { opacity: 0.75; outline: 2px solid #d64545; outline-offset: 1px; }
.sc__meta { display: flex; justify-content: flex-end; gap: 4px; margin-top: 2px; font-size: 11px; color: #6b6880; }
.is-mine > .sc__bubble .sc__meta { color: rgba(255, 255, 255, 0.9); }
.sc__bubble.has-img .sc__meta { padding-right: 6px; }
.sc__tick { font-style: normal; }
.sc__sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
.sc__bubble a { color: inherit; font-weight: 600; text-decoration: underline; text-underline-offset: 2px; }
.sc__row:not(.is-mine) .sc__bubble a { color: #3B1782; }
@media (prefers-reduced-motion: reduce) { .sc__row { animation: none; } }
`;

const TICK = { sending: "◷", sent: "✓✓", failed: "!" } as const;
const TICK_SR = { sending: "Enviando", sent: "Enviado", failed: "No enviado" } as const;

export interface ChatBubbleProps {
  /** Texto del mensaje (puede llevar enlaces u otros nodos). */
  children?: ReactNode;
  /** true: mensaje tuyo (a la derecha, violeta). */
  mine?: boolean;
  /** Lo que se lee bajo el mensaje: la hora («10:33») o «Tú · 9:10». */
  time: string;
  /** Quién lo envió, solo para lectores de pantalla («Tú» o el código de la contraparte). */
  sender?: string;
  /** Estado del envío de un mensaje tuyo; muestra su ícono junto a la hora. */
  status?: "sending" | "sent" | "failed";
  /** No es el primero de su ráfaga: se pega al anterior. */
  cont?: boolean;
  /** No es el último de su ráfaga. */
  more?: boolean;
  /** Oculta la hora (dentro de una ráfaga, salvo la última). */
  hideTime?: boolean;
  /** URL de una imagen enviada. */
  image?: string;
  /** Clase extra para la fila. */
  className?: string;
  /** Lo que va debajo de la burbuja, dentro de la fila (p. ej. «No se pudo enviar · Reintentar»). */
  footer?: ReactNode;
}

export function ChatBubble({ children, mine = false, time, sender, status, cont = false, more = false, hideTime = false, image, className, footer }: ChatBubbleProps): JSX.Element {
  const tick = mine && status;
  return <>
    <style href="concorde-chat-bubble" precedence="default">{CHAT_BUBBLE_CSS}</style>
    <div className={`sc__row${className ? ` ${className}` : ""}${mine ? " is-mine" : ""}${cont ? " is-cont" : ""}${more ? " is-more" : ""}`}>
      <div className={`sc__bubble${status ? ` is-${status}` : ""}${image ? " has-img" : ""}`}>
        {sender ? <span className="sc__sr">{sender}: </span> : null}
        {image ? <img src={image} alt="Imagen enviada" /> : null}
        {children ? <p>{children}</p> : null}
        {hideTime ? null : <span className="sc__meta">{time}{tick ? <>
          <i className="sc__tick" aria-hidden>{TICK[status]}</i>
          <span className="sc__sr">{TICK_SR[status]}</span></> : null}</span>}
      </div>
      {footer}
    </div>
  </>;
}

export default ChatBubble;
