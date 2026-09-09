'use client';

/** Serialises the inline SVG diagram and hands it over as a file. */
export function DownloadDiagramButton() {
  const download = () => {
    const svg = document.querySelector<SVGSVGElement>('.diagram svg');
    if (!svg) return;
    const clone = svg.cloneNode(true) as SVGSVGElement;
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('width', '880');
    clone.setAttribute('height', '730');
    const blob = new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'relay-architecture.svg';
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <button className="btn sec" onClick={download}>
      Download diagram
    </button>
  );
}
