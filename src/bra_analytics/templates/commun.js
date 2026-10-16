/* Aides partagees par les ecrans a graphes (fiche, comparaison) : pures, sans etat.
   Inserees dans la page par le marqueur de gabarit (dashboard.injecter). */
const NS = "http://www.w3.org/2000/svg";
const DAY = 86400000;
const NIVEAUX = ["Faible", "Limité", "Marqué", "Fort", "Très fort"];
const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const $ = id => document.getElementById(id);
const fr = n => n == null ? "—" : String(n).replace(".", ",");
const dateFr = iso => { const [y, m, d] = iso.split("-").map(Number); return `${d} ${MOIS[m - 1]} ${y}`; };
const pad = n => String(n).padStart(2, "0");
const T0 = iso => Date.parse(iso + "T00:00:00Z");
const mmdd = ms => { const d = new Date(ms); return pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate()); };
const nombres = s => s == null ? [] : s.split(",").map(v => v === "" ? null : +v);
function el(nom, attrs, parent) {
  const n = document.createElementNS(NS, nom);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(n);
  return n;
}
function chemin(points) {           // points : [x, y] ou null ; un null rompt le trait
  let d = "", ouvert = false;
  for (const p of points) {
    if (!p) { ouvert = false; continue; }
    d += (ouvert ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1);
    ouvert = true;
  }
  return d;
}
