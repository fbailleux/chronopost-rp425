#!/opt/homebrew/bin/python3
"""Imprime le bon d'envoi Chronopost (PDF) sur la Rongta RP425 en 4x6 pouces.

Usage :
    imprimer_etiquette.py [fichier.pdf] [--sans-impression] [--sans-dialogue]

Sans fichier : prend le PDF « bon d'envoi » le plus récent de ~/Downloads.
Étapes : repérer le cadre de l'étiquette, générer le ZPL compressé (RLE),
afficher l'aperçu, demander confirmation, imprimer.
"""
import glob
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

W, H, RB = 812, 1218, 102          # 4x6 pouces à 203 dpi, 102 octets par ligne
FILE_PAR_DEFAUT = "_RP425_ZPL_203DPI_"
DOSSIER = os.path.dirname(os.path.abspath(__file__))
SORTIE = os.path.join(DOSSIER, "dernier")


def outil(nom):
    chemin = shutil.which(nom) or os.path.join("/opt/homebrew/bin", nom)
    if not os.path.exists(chemin):
        chemin = os.path.join("/usr/local/bin", nom)
    if not os.path.exists(chemin):
        raise SystemExit("Outil introuvable : %s (installer poppler : brew install poppler)" % nom)
    return chemin


def dialogue(texte, boutons, defaut, titre="Étiquette Chronopost RP425"):
    """Renvoie le bouton cliqué, ou None si annulé."""
    liste = ", ".join('"%s"' % b for b in boutons)
    script = 'display dialog "%s" with title "%s" buttons {%s} default button "%s" cancel button "%s"' % (
        texte.replace('"', "'"), titre, liste, defaut, boutons[0])
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    m = re.search(r"button returned:(.*?)(?:,|$)", r.stdout.strip())
    return m.group(1).strip() if m else None


def erreur(texte):
    sys.stderr.write(texte + "\n")
    if "--sans-dialogue" not in sys.argv:
        subprocess.run(["osascript", "-e",
                        'display dialog "%s" with title "Étiquette Chronopost RP425" buttons {"OK"} default button "OK" with icon stop'
                        % texte.replace('"', "'")], capture_output=True)
    sys.exit(1)


def trouver_pdf(args):
    for a in args:
        if not a.startswith("--") and a.lower().endswith(".pdf"):
            return a
    candidats = glob.glob(os.path.expanduser("~/Downloads/*.pdf"))
    candidats = [c for c in candidats if re.search(r"chronopost|chrono|envoi|colis", os.path.basename(c), re.I)]
    if not candidats:
        erreur("Aucun bon d'envoi trouvé dans Téléchargements. Glisse le PDF sur l'application.")
    return max(candidats, key=os.path.getmtime)


def pgm(chemin):
    d = open(chemin, "rb").read()
    m = re.match(rb"P5\s+(\d+)\s+(\d+)\s+255\s", d)
    w, h = int(m.group(1)), int(m.group(2))
    return w, h, d[len(d) - w * h:]


def encadré(img, w, h, zx0, zx1, zy0, zy1, min_ligne, min_colonne):
    """Plus grand rectangle tracé dans la zone : (x0, y0, largeur, hauteur) en pixels, ou None."""
    sombre = bytes(1 if i < 200 else 0 for i in range(256))
    lignes = []
    for y in range(zy0, zy1):
        s = img[y * w + zx0:y * w + zx1].translate(sombre)
        if max((len(m.group()) for m in re.finditer(rb"\x01+", s)), default=0) > min_ligne:
            lignes.append(y)
    colonnes, haut, bas = [], h, 0
    for x in range(zx0, zx1):
        s = img[zy0 * w + x:zy1 * w:w].translate(sombre)
        trait = max(re.finditer(rb"\x01+", s), key=lambda m: len(m.group()), default=None)
        if trait and len(trait.group()) > min_colonne:
            colonnes.append(x)
            haut, bas = min(haut, zy0 + trait.start()), max(bas, zy0 + trait.end())
    # La hauteur vient des montants du cadre : un trait horizontal voisin (autre encadré) ne l'allonge pas
    lignes = [y for y in lignes if haut - 2 <= y <= bas + 2]
    if len(lignes) < 2 or len(colonnes) < 2:
        return None
    x0 = min(colonnes)
    return x0, haut, max(colonnes) - x0 + 2, bas - haut + 2


def repérer(pdf, tmp):
    """Bon Chronopost en A4 paysage, pixels à 288 dpi.
    Étiquette : grand cadre de la moitié droite (rapport ~1,31, tient en largeur dans le 4x6).
    Fiche destinataire : cadre du quart haut gauche, imprimé tourné d'un quart de tour."""
    base = os.path.join(tmp, "page")
    subprocess.run([outil("pdftoppm"), "-r", "288", "-gray", "-singlefile", pdf, base], check=True)
    w, h, img = pgm(base + ".pgm")
    if w < h:
        erreur("Ce PDF n'est pas en paysage : ce n'est pas la mise en page Chronopost attendue. Rien imprimé.")
    etiquette = encadré(img, w, h, int(w * 0.55), w, 0, h, 0.3 * w, 0.5 * h)
    if etiquette is None:
        erreur("Cadre de l'étiquette introuvable : ce PDF n'a pas la mise en page Chronopost attendue.")
    rapport = etiquette[3] / etiquette[2]
    if not 1.2 <= rapport <= H / W:
        erreur("Le cadre détecté n'entre pas dans le 4x6 (rapport %.2f, attendu entre 1,20 et 1,50). Rien imprimé." % rapport)
    fiche = encadré(img, w, h, 0, int(w * 0.35), 0, h // 2, 0.2 * w, 0.3 * h)
    if fiche is None:
        erreur("Cadre de la fiche destinataire introuvable : ce PDF n'a pas la mise en page Chronopost attendue.")
    return etiquette, fiche


def rendre(pdf, tmp, nom, dpi, x, y, lw, lh):
    base = os.path.join(tmp, nom)
    subprocess.run([outil("pdftoppm"), "-r", repr(dpi), "-x", str(x), "-y", str(y), "-W", str(lw), "-H", str(lh),
                    "-gray", "-singlefile", pdf, base], check=True)
    w, h, img = pgm(base + ".pgm")
    return w, h, img


def binariser(g, gw, gh, seuil, ox=0, oy=0, trame=None):
    """trame=(bas, haut) : les gris de cet intervalle deviennent un point sur quatre,
    pour qu'un texte blanc posé sur un aplat gris reste lisible."""
    b = bytearray(W * H)
    for y in range(min(gh, H - oy)):
        lig = g[y * gw:(y + 1) * gw]
        base = (y + oy) * W + ox
        for x in range(min(gw, W - ox)):
            v = lig[x]
            if trame and trame[0] <= v <= trame[1]:
                b[base + x] = 1 if x % 2 == 0 and y % 2 == 0 else 0
            elif v < seuil:
                b[base + x] = 1
    return b


def tourner_gauche(g, gw, gh):
    """Quart de tour dans le sens inverse des aiguilles d'une montre : (gh, gw, image)."""
    r = bytearray(gw * gh)
    for y in range(gh):
        lig = g[y * gw:(y + 1) * gw]
        for x in range(gw):
            r[(gw - 1 - x) * gh + y] = lig[x]
    return gh, gw, bytes(r)


def cadre_noir(b, y0=0, y1=H, epaisseur=3):
    for y in range(y0, y1):
        for x in range(W):
            if x < epaisseur or x >= W - epaisseur or y < y0 + epaisseur or y >= y1 - epaisseur:
                b[y * W + x] = 1


def lignes_hex(b):
    out = []
    for y in range(H):
        r = bytearray()
        for xb in range(RB):
            v = 0
            for k in range(8):
                x = xb * 8 + k
                v = (v << 1) | (b[y * W + x] if x < W else 0)
            r.append(v)
        out.append(r.hex().upper())
    return out


def _nombre(n):
    s = ""
    while n >= 400:
        s += "z"
        n -= 400
    if n >= 20:
        s += chr(ord("g") + n // 20 - 1)
        n %= 20
    if n:
        s += chr(ord("G") + n - 1)
    return s


def _ligne_rle(row):
    if set(row) == {"0"}:
        return ","
    if set(row) == {"F"}:
        return "!"
    queue = ""
    t = row.rstrip("0")
    if len(row) - len(t) > 0 and t:
        row, queue = t, ","
    else:
        t2 = row.rstrip("F")
        if len(row) - len(t2) > 0 and t2:
            row, queue = t2, "!"
    out, i = "", 0
    while i < len(row):
        j = i
        while j < len(row) and row[j] == row[i]:
            j += 1
        n = j - i
        out += (_nombre(n) + row[i]) if n > 1 else row[i]
        i = j
    return out + queue


def decoder(flux):
    """Décodeur indépendant du RLE ZPL, pour vérifier ce qu'on envoie."""
    out, cur, prev, n, i = [], "", "", 0, 0
    while len(out) < H and i < len(flux):
        c = flux[i]
        i += 1
        if c == ":":
            out.append(prev)
            continue
        if c in ",!":
            cur += ("0" if c == "," else "F") * (2 * RB - len(cur))
            out.append(cur)
            prev, cur, n = cur, "", 0
            continue
        if c in "0123456789ABCDEF":
            cur += c * max(n, 1)
            n = 0
        elif "g" <= c <= "z":
            n += 20 * (ord(c) - ord("g") + 1)
        elif "G" <= c <= "Y":
            n += ord(c) - ord("G") + 1
        if len(cur) == 2 * RB:
            out.append(cur)
            prev, cur = cur, ""
    return out


def vers_zpl(b):
    lignes = lignes_hex(b)
    flux, prec = "", None
    for r in lignes:
        flux += ":" if r == prec else _ligne_rle(r)
        prec = r
    if decoder(flux) != lignes:
        erreur("Vérification interne échouée : la compression ZPL ne redonne pas l'image. Rien imprimé.")
    total = RB * H
    return ("^XA\n^MMT\n^PW%d\n^LL%d\n^LS0\n^LH0,0\n^FO0,0^GFA,%d,%d,%d,%s^FS\n^PQ1,0,1,N\n^XZ\n"
            % (W, H, total, total, RB, flux)), flux


def png_1bit(images):
    """Aperçu : plusieurs images 812x1218 côte à côte, séparées de 40 points gris."""
    sep = 40
    largeur = len(images) * W + (len(images) - 1) * sep
    raw = bytearray()
    for y in range(H):
        raw.append(0)
        ligne = bytearray(largeur)
        for k, b in enumerate(images):
            o = k * (W + sep)
            for x in range(W):
                ligne[o + x] = 0 if b[y * W + x] else 1
            for x in range(W, W + sep if k < len(images) - 1 else W):
                if o + x < largeur:
                    ligne[o + x] = 0 if (x - W) % 2 == 0 and y % 2 == 0 else 1
        for xb in range((largeur + 7) // 8):
            v = 0
            for kk in range(8):
                x = xb * 8 + kk
                v = (v << 1) | (ligne[x] if x < largeur else 1)
            raw.append(v)

    def bloc(t, s):
        return struct.pack(">I", len(s)) + t + s + struct.pack(">I", zlib.crc32(t + s) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", struct.pack(">IIBBBBB", largeur, H, 1, 0, 0, 0, 0))
            + bloc(b"IDAT", zlib.compress(bytes(raw), 9)) + bloc(b"IEND", b""))


def file_par_defaut():
    r = subprocess.run(["lpstat", "-d"], capture_output=True, text=True)
    m = re.search(r":\s*(\S+)\s*$", r.stdout.strip())
    return m.group(1) if m else FILE_PAR_DEFAUT


def main():
    args = sys.argv[1:]
    pdf = trouver_pdf(args)
    os.makedirs(SORTIE, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        (x0, y0, fw, fh), (fx0, fy0, ffw, ffh) = repérer(pdf, tmp)

        # Étiquette : le cadre prend toute la largeur du 4x6, sans déformation, centré en hauteur
        dpi = 288 * W / fw
        lh = min(H, round(fh * dpi / 288))
        haut = (H - lh) // 2
        gw, gh, g = rendre(pdf, tmp, "etiquette", dpi, round(x0 * dpi / 288), round(y0 * dpi / 288), W, lh)
        etiquette = binariser(g, gw, gh, 170, oy=haut)
        cadre_noir(etiquette, haut, haut + lh)
        zpl_e, _ = vers_zpl(etiquette)

        # Fiche destinataire : redressée d'un quart de tour, ajustée dans le 4x6 avec 20 points de marge
        marge = 20
        echelle = min((W - 2 * marge) / ffh, (H - 2 * marge) / ffw)
        dpi_f = 288 * echelle
        cw, ch = round(ffw * echelle), round(ffh * echelle)
        fg, fgh, fgg = rendre(pdf, tmp, "fiche", dpi_f, round(fx0 * echelle), round(fy0 * echelle), cw, ch)
        fg, fgh, fgg = tourner_gauche(fgg, fg, fgh)
        fiche = binariser(fgg, fg, fgh, 140, ox=marge, oy=marge, trame=(150, 195))
        zpl_f, _ = vers_zpl(fiche)

    fichiers = {
        "etiquette": os.path.join(SORTIE, "etiquette-4x6.zpl"),
        "fiche": os.path.join(SORTIE, "fiche-4x6.zpl"),
    }
    open(fichiers["etiquette"], "w").write(zpl_e)
    open(fichiers["fiche"], "w").write(zpl_f)
    apercu = os.path.join(SORTIE, "apercu.png")
    open(apercu, "wb").write(png_1bit([etiquette, fiche]))
    print("PDF :", pdf)
    print("ZPL :", fichiers["etiquette"], len(zpl_e), "octets;", fichiers["fiche"], len(zpl_f), "octets")
    print("Aperçu :", apercu)

    if "--sans-impression" in args:
        return
    if len(zpl_e) > 60000 or len(zpl_f) > 60000:
        erreur("Fichier ZPL trop gros (> 60 Ko) : l'imprimante le tronquerait. Rien imprimé.")

    choix = "Étiquette seule"
    if "--sans-dialogue" not in args:
        subprocess.run(["open", "-a", "Preview", apercu])
        choix = dialogue(
            "Aperçu ouvert (étiquette à gauche, fiche destinataire à droite). Que faut-il imprimer ?",
            ["Annuler", "Étiquette + fiche", "Étiquette seule"], "Étiquette seule")
        if choix is None or choix == "Annuler":
            print("Annulé, rien imprimé.")
            return
    file_ = file_par_defaut()
    envois = [fichiers["etiquette"]] + ([fichiers["fiche"]] if choix == "Étiquette + fiche" else [])
    for f in envois:
        r = subprocess.run(["lpr", "-P", file_, "-o", "raw", f], capture_output=True, text=True)
        if r.returncode != 0:
            erreur("L'envoi à l'imprimante a échoué : " + (r.stderr.strip() or "erreur lpr"))
    print("Envoyé à", file_, ":", len(envois), "travail(aux).")
    if "--sans-dialogue" not in args:
        subprocess.run(["osascript", "-e",
                        'display notification "%d étiquette(s) envoyée(s) à l\'imprimante" with title "Étiquette Chronopost RP425"'
                        % len(envois)], capture_output=True)


if __name__ == "__main__":
    main()
