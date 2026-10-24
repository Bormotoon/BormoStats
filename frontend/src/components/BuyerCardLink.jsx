import { ArrowSquareOut } from "@phosphor-icons/react";
import { buyerCardUrl, marketplaceName } from "../utils/formats.js";

/** The supplier article as a link to the card on the marketplace, in a new tab. */
export default function BuyerCardLink({ marketplace, productId, children }) {
  const url = buyerCardUrl(marketplace, productId);
  if (!url) return <span className="font-mono text-xs">{children}</span>;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      title={`Открыть карточку на ${marketplaceName(marketplace)} как покупатель`}
      className="inline-flex items-center gap-1 font-mono text-xs text-[var(--color-primary)] hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)] rounded"
    >
      {children}
      <ArrowSquareOut size={12} aria-hidden="true" className="shrink-0" />
    </a>
  );
}
