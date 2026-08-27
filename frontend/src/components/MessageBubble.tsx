import type { Message } from "@/lib/types";
import { formatTimestamp, linkify, SYSTEM_EVENT_LABEL } from "@/lib/format";
import { ImageIcon } from "@/components/icons";

/**
 * RF-034/036: texto con enlaces clicables + timestamp por mensaje. RF-039 excluye a propósito
 * edición/borrado, búsqueda y "escribiendo" — no agregar esas afordancias aquí.
 */
export default function MessageBubble({ message }: { message: Message }) {
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

  const isAdvisor = message.sender_type === "ADVISOR";
  const align = isAdvisor ? "items-end" : "items-start";
  const bubbleColor = isAdvisor
    ? "bg-[color:var(--vmc-color-vault-500)] text-white"
    : message.sender_type === "BOT"
      ? "bg-neutral-100 text-[#191C1C]"
      : "bg-white text-[#191C1C] shadow-sm";

  return (
    <div className={`flex flex-col ${align} gap-1`}>
      <div className={`max-w-md rounded-2xl px-4 py-2.5 ${bubbleColor}`}>
        {message.message_type === "IMAGE" ? (
          <p className="flex items-center gap-1.5 text-sm italic opacity-80">
            <ImageIcon width={16} height={16} /> Imagen adjunta
          </p>
        ) : (
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
        )}
      </div>
      <span className="px-1 text-[11px] text-neutral-500">{formatTimestamp(message.created_at)}</span>
    </div>
  );
}
