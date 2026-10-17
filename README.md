# Étiquette Chronopost sur une Rongta RP425

Un script pour imprimer le bon d'envoi Chronopost sur une imprimante d'étiquettes Rongta RP425, depuis un Mac, au format 4×6 pouces. Tu vois l'aperçu avant que la moindre étiquette sorte.

Écrit en Python 3 pour le script, en AppleScript pour le lanceur et en shell pour la construction de l'application. Pas de Swift ici.

Dérivé de [mondial-relay-rp425](https://github.com/fbailleux/mondial-relay-rp425) : même chaîne (repérage du cadre, ZPL compressé, aperçu, confirmation).

## Mise en page attendue

Calée sur un bon Chronopost Shop2Shop (Chrono Relais) généré par leboncoin : A4 paysage.

- **Étiquette** : le grand cadre de la moitié droite. Il fait environ 110 × 144 mm (rapport 1,31). Le script le réduit pour laisser 3 mm de chaque côté du papier et le centre en hauteur, sans le déformer.
- **Fiche destinataire** : le cadre en haut à gauche, imprimé de travers (un quart de tour) sur le bon. Le script la redresse. Son bandeau gris passe en trame légère, sinon il sort noir et le texte blanc disparaît.
- L'aide-mémoire et le reçu de l'expéditeur, au centre et en bas à gauche, ne sont pas imprimés.

Un autre modèle de bon Chronopost (Chrono 13, Chrono Classic, bon fait depuis chronopost.fr) n'a pas été essayé. Si la mise en page diffère, le script s'arrête sans rien imprimer.

## Ce que ça fait

1. Il prend le PDF que tu lui donnes, ou le bon d'envoi le plus récent de ton dossier Téléchargements (nom contenant « chronopost », « chrono », « envoi » ou « colis »).
2. Il repère le cadre de l'étiquette et le dessine à 203 dpi, à la taille du papier moins 3 mm sur les côtés.
3. Il ouvre un aperçu : l'étiquette à gauche, la fiche destinataire à droite.
4. Il te demande : annuler, étiquette seule, ou étiquette et fiche. Rien ne part avant ton clic.
5. Il envoie le ZPL compressé à l'imprimante par défaut (`lpr -o raw`).

## Ce qu'il te faut

- macOS, avec Python 3 de Homebrew (`/opt/homebrew/bin/python3`)
- poppler : `brew install poppler`
- une Rongta RP425 branchée en USB, avec son pilote ZPL 203 dpi, définie comme imprimante par défaut
- du papier thermique direct en 4×6 pouces (101,6 × 152,4 mm), face thermique vers le haut

## Utilisation

```bash
./construire_app.sh
```

Tu obtiens `Imprimer étiquette Chronopost.app`. Double-clic, ou glisse le PDF dessus. Sans l'appli :

```bash
python3 imprimer_etiquette.py bon-d-envoi.pdf
python3 imprimer_etiquette.py bon-d-envoi.pdf --sans-impression   # génère seulement le ZPL et l'aperçu
```

Les fichiers générés vont dans `dernier/` (ignoré par git).

## Pour mettre ta propre icône

Dépose un fichier `icone.icns` dans le dossier avant de lancer `construire_app.sh`. Le logo Chronopost n'est pas dans le dépôt, c'est une marque.

## Les pièges rencontrés

- **L'imprimante tronque à environ 64 Ko.** Une image envoyée en hexadécimal brut pèse 248 Ko : l'étiquette sort coupée à 26 % de la hauteur, sans aucune erreur. Le script compresse en RLE ZPL (36 Ko) et refuse d'imprimer au-delà de 60 Ko.
- **Étiquette vide.** En thermique direct, seule une face réagit. Gratte l'étiquette avec l'ongle : la bonne face noircit.
- **Bord droit tronqué.** Calée au ras du papier, l'étiquette perdait son cadre et la fin des lignes côté droit. Avec 3 mm de marge de chaque côté, elle sort entière.
- **Cadre fin qui disparaît.** Le script redessine le cadre sur 3 points d'épaisseur, au cas où le papier bouge d'un demi-millimètre.

## Garde-fous

Le script refuse d'imprimer si le PDF n'est pas en paysage, si l'un des deux cadres est introuvable, si le cadre de l'étiquette n'entre pas dans le 4×6 (rapport hors de 1,20 à 1,50), si le ZPL dépasse 60 Ko, ou si la compression ne redonne pas exactement l'image d'origine (il décode son propre flux pour le vérifier).

## Limites

- Testé sur un seul modèle de bon d'envoi (Shop2Shop via leboncoin) et une seule imprimante, la RP425 en 203 dpi.
- Aucun bon d'envoi réel dans ce dépôt : il contient des noms et des adresses, il reste sur ta machine.
- Projet indépendant, sans lien avec Chronopost ni Rongta.

## Licence

MIT.
