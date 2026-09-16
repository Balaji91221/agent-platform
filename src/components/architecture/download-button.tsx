'use client';

import { DownloadIcon } from '../icons';

/**
 * Serialises the inline SVG and hands it over as a file. Size comes from the
 * live viewBox, so re-laying out the diagram cannot leave a wrong export.
 */
export function DownloadDiagramButton() {
  const download = () => {
    const svg = document.querySelector<SVGSVGElement>('.diagram svg');
    if (!svg) return;

    const box = svg.viewBox.baseVal;
    const clone = svg.cloneNode(true) as SVGSVGElement;
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('width', String(box.width || svg.clientWidth));
    clone.setAttribute('height', String(box.height || svg.clientHeight));

    const blob = new Blob([new XMLSerializer().serializeToString(clone)], {
      type: 'image/svg+xml',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'relay-architecture.svg';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <button className="btn sec" onClick={download}>
      <DownloadIcon />
      Download SVG
    </button>
  );
}
