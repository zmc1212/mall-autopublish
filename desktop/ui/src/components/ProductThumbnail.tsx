import { FileText } from "lucide-react";
import { useState } from "react";

import { api } from "../api";

export default function ProductThumbnail({ url, title }: { url?: string; title: string }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);

  return (
    <span className="run-product-thumbnail">
      {url && failedUrl !== url ? (
        <img
          src={api.previewUrl(url)}
          alt={`${title} 主图预览`}
          loading="lazy"
          decoding="async"
          onError={() => setFailedUrl(url)}
        />
      ) : <FileText aria-label="暂无主图预览" role="img" />}
    </span>
  );
}
