// Reelfold brand mark for the app chrome (sidebar header, first run). Generated from video-studio-app/brand/round3/
// reelfold (symbol-on-dark / symbol-on-light, wordmark-text-only): inline SVG so it follows the theme through CSS
// variables (--brand-sun: the front card, --brand-cut: the cards behind it; the wordmark is currentColor) and needs no
// asset loader.
import { useId } from 'react';

const CARD = 'M459.86,371 H564.14 A26.86,26.86 0 0 1 591,397.86 V626.14 A26.86,26.86 0 0 1 564.14,653 H459.86 A26.86,26.86 0 0 1 433,626.14 V397.86 A26.86,26.86 0 0 1 459.86,371 Z';
/** the fan, back to front: each card is cut out where the cards in front of it (stroked 40 units) overlap it */
const ANGLES = [-30, -10, 10, 30];
const rot = (a: number) => `rotate(${a} 512 853)`;

/** Four vertical clip cards fanned out from one point; the front one (teal) is the clip QC flagged for you. */
export function BrandSymbol({ size = 22 }: { size?: number }) {
  const id = useId().replace(/:/g, '');
  return (
    <svg className="brand-symbol" width={size} height={(size * 404) / 668} viewBox="0 0 668 404" aria-hidden="true">
      <defs>
        {ANGLES.map((_, i) => (
          <mask key={i} id={`${id}m${i}`} maskUnits="userSpaceOnUse" x="-500" y="-500" width="2024" height="2024">
            <rect x="-500" y="-500" width="2024" height="2024" fill="#fff" />
            {ANGLES.slice(i + 1).map((a) => (
              <path key={a} d={CARD} transform={rot(a)} fill="#000" stroke="#000" strokeWidth={40} strokeLinejoin="round" />
            ))}
          </mask>
        ))}
      </defs>
      <g transform="translate(-177.8 -339.8)">
        {ANGLES.map((a, i) => (
          <g key={a} mask={`url(#${id}m${i})`}>
            <path d={CARD} transform={rot(a)} fill={i === ANGLES.length - 1 ? 'var(--brand-sun)' : 'var(--brand-cut)'} />
          </g>
        ))}
      </g>
    </svg>
  );
}

const WORD = 'M37.2 177.5V68.4H62.1V86.5H63.3Q66.2 77.1 73.5 71.9Q80.8 66.8 90.2 66.8Q92.3 66.8 95 67Q97.7 67.2 99.5 67.5V91.1Q97.8 90.6 94.3 90.1Q90.7 89.7 87.5 89.7Q80.4 89.7 74.9 92.7Q69.3 95.7 66.1 101Q62.9 106.4 62.9 113.3V177.5ZM156.7 179.6Q140.3 179.6 128.4 172.7Q116.5 165.8 110.1 153.2Q103.7 140.6 103.7 123.5Q103.7 106.7 110.1 94Q116.5 81.2 128.1 74.1Q139.7 66.9 155.4 66.9Q165.4 66.9 174.4 70.2Q183.4 73.4 190.3 80.1Q197.3 86.9 201.2 97.3Q205.2 107.7 205.2 122.1V130H115.8V112.6H180.5Q180.5 105.2 177.4 99.4Q174.3 93.6 168.7 90.3Q163.1 87 155.7 87Q147.8 87 141.8 90.8Q135.9 94.5 132.6 100.7Q129.3 106.8 129.2 114.2V129.3Q129.2 138.8 132.7 145.6Q136.1 152.4 142.4 156Q148.6 159.6 157.1 159.6Q162.6 159.6 167.2 158Q171.8 156.4 175.1 153.2Q178.4 150.1 180.1 145.5L204.2 148.2Q201.9 157.7 195.5 164.7Q189.1 171.8 179.3 175.7Q169.4 179.6 156.7 179.6ZM271.7 179.6Q255.2 179.6 243.3 172.7Q231.4 165.8 225 153.2Q218.6 140.6 218.6 123.5Q218.6 106.7 225.1 94Q231.5 81.2 243.1 74.1Q254.7 66.9 270.3 66.9Q280.4 66.9 289.3 70.2Q298.3 73.4 305.3 80.1Q312.2 86.9 316.2 97.3Q320.1 107.7 320.1 122.1V130H230.7V112.6H295.5Q295.4 105.2 292.3 99.4Q289.2 93.6 283.6 90.3Q278 87 270.6 87Q262.7 87 256.8 90.8Q250.8 94.5 247.5 100.7Q244.2 106.8 244.2 114.2V129.3Q244.2 138.8 247.6 145.6Q251.1 152.4 257.3 156Q263.6 159.6 272 159.6Q277.6 159.6 282.1 158Q286.7 156.4 290 153.2Q293.3 150.1 295.1 145.5L319.1 148.2Q316.8 157.7 310.5 164.7Q304.1 171.8 294.2 175.7Q284.4 179.6 271.7 179.6ZM364 32V177.5H338.2V32ZM442.1 68.4V88.3H377.6V68.4ZM393.7 177.5V58.1Q393.7 47.1 398.3 39.8Q402.9 32.5 410.6 28.8Q418.3 25.2 427.8 25.2Q434.5 25.2 439.7 26.2Q444.8 27.3 447.3 28.1L442.2 48.1Q440.6 47.6 438.1 47Q435.6 46.5 432.6 46.5Q425.4 46.5 422.4 49.9Q419.4 53.4 419.4 59.8V177.5ZM502.1 179.6Q486.1 179.6 474.4 172.6Q462.7 165.5 456.2 152.9Q449.8 140.2 449.8 123.4Q449.8 106.4 456.2 93.7Q462.7 81 474.4 74Q486.1 66.9 502.1 66.9Q518.1 66.9 529.8 74Q541.5 81 547.9 93.7Q554.4 106.4 554.4 123.4Q554.4 140.2 547.9 152.9Q541.5 165.5 529.8 172.6Q518.1 179.6 502.1 179.6ZM502.2 159Q510.9 159 516.7 154.2Q522.5 149.4 525.4 141.3Q528.3 133.2 528.3 123.2Q528.3 113.3 525.4 105.1Q522.5 97 516.7 92.2Q510.9 87.3 502.2 87.3Q493.4 87.3 487.5 92.2Q481.7 97 478.8 105.1Q475.9 113.3 475.9 123.2Q475.9 133.2 478.8 141.3Q481.7 149.4 487.5 154.2Q493.4 159 502.2 159ZM598.2 32V177.5H572.5V32ZM661.5 179.4Q648.7 179.4 638.5 172.8Q628.3 166.2 622.5 153.6Q616.6 141 616.6 123.1Q616.6 104.9 622.6 92.3Q628.6 79.8 638.8 73.4Q649 66.9 661.6 66.9Q671.2 66.9 677.4 70.2Q683.5 73.4 687.2 77.9Q690.8 82.5 692.8 86.4H693.8V32H719.6V177.5H694.3V160.2H692.8Q690.7 164.2 687 168.7Q683.3 173.2 677.1 176.3Q670.9 179.4 661.5 179.4ZM668.7 158.3Q676.9 158.3 682.6 153.9Q688.3 149.4 691.3 141.5Q694.4 133.5 694.4 122.9Q694.4 112.3 691.4 104.5Q688.4 96.7 682.7 92.3Q677 88 668.7 88Q660.1 88 654.4 92.5Q648.6 97 645.7 104.9Q642.8 112.8 642.8 122.9Q642.8 133.1 645.7 141.1Q648.7 149.1 654.4 153.7Q660.2 158.3 668.7 158.3Z';

/** "reelfold" (lowercase wordmark, outlined); colour = currentColor. */
export function BrandWordmark({ height = 22 }: { height?: number }) {
  return (
    <svg className="brand-word" height={height} width={(height * 692) / 165} viewBox="32 20 692 165" aria-hidden="true">
      <path d={WORD} fill="currentColor" />
    </svg>
  );
}
