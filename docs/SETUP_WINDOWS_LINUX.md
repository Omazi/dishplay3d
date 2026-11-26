# Calculateur DishPlay Scan — installation Windows / Linux

Le calculateur est le PC qui reconstruit le plat pendant que l'iPhone filme. Aucun GPU, aucun Mac et aucune
licence payante ne sont nécessaires. Mesuré ici : Linux x86-64, 4 cœurs, sans GPU (voir `TEST_REPORT.md`).

## Prérequis
- Python **3.12** (Windows : installateur python.org, cocher « Add to PATH » ; Linux : `python3.12` + `python3.12-venv`).
- ~1,5 Go d'espace pour l'environnement Python (Open3D tire des dépendances lourdes), + ~100–300 Mo par scan
  (voir « Place sur le disque » plus bas).
- iPhone et PC sur **le même Wi‑Fi**, sans « isolation des clients » (souvent active sur les réseaux invités).
- 8 Go de RAM conseillés (pic mesuré à confirmer sur votre PC : `tools/doctor.py`).

## Windows (recommandé : Python natif, sans WSL)
```powershell
git clone https://github.com/Omazi/dishplay3d.git
cd dishplay3d
```
Puis **double-cliquer sur `Demarrer-le-calculateur.cmd`** (la fenêtre reste ouverte à la fin, pour lire un
éventuel message). En ligne de commande : `powershell -ExecutionPolicy Bypass -File .\start-calculator.ps1`.

Le premier lancement vérifie que Python 3.12 est là (sinon il dit où l'installer), crée `backend\.venv`, installe
`requirements.lock`, télécharge le modèle de profondeur (99 Mo), demande **une fois** l'accord de Windows pour
ajouter une règle de pare-feu (port TCP 8765, réseaux privés seulement), lance le diagnostic puis le calculateur.
Si l'accord est refusé, le calculateur démarre quand même et le script explique comment ajouter la règle.
Le réseau Wi‑Fi doit être déclaré « Privé » dans Windows (Paramètres › Réseau › Propriétés).

Ce script est exécuté sur une machine Windows de GitHub à chaque modification (travail « calculator on
Windows ») : installation, règle de pare-feu, tests du calculateur et un scan complet de synthèse.
Jusqu'au 24 novembre il n'avait jamais été exécuté, et sa ligne de pare-feu ne pouvait pas créer la règle
(Windows redemandait l'accord à chaque démarrage).

**WSL2** : en mode NAT par défaut, l'iPhone ne peut pas joindre le serveur. Utiliser Python natif (ci‑dessus) ou
activer `networkingMode=mirrored` dans `%UserProfile%\.wslconfig` (Windows 11 22H2+), puis `./start-calculator.sh`.

## Linux
```bash
git clone https://github.com/Omazi/dishplay3d.git && cd dishplay3d
./start-calculator.sh            # options : --port 8765 --data ~/dishplay-scan-data
```
Pare-feu (ufw) : `sudo ufw allow from 192.168.0.0/16 to any port 8765 proto tcp`.

## Mettre à jour le calculateur
L'app se met à jour seule par TestFlight ; le calculateur, non. Après chaque nouvelle version annoncée :
1. fermer la fenêtre du calculateur ;
2. dans le dossier du projet : `git pull` ;
3. relancer `start-calculator.ps1` (Windows) ou `./start-calculator.sh` (Linux) : il réinstalle ce qui a changé.

Pour savoir quelle version tourne : dans l'app, Réglages affiche « moteur p1-… » ; la version actuelle est
**p1-0.11.0**. Un calcul en cours au moment de l'arrêt n'est pas perdu : il reprend au démarrage suivant.

## Ce que le calculateur affiche au démarrage
- le dossier des données et la place libre sur son disque ;
- le **code de jumelage** (6 chiffres, renouvelé à chaque démarrage) et l'adresse `https://<IP-du-PC>:8765`
  (avec plusieurs cartes réseau ou un VPN, la première adresse est celle que l'iPhone joint le plus probablement) ;
- l'**empreinte du certificat** auto-signé (créé dans `~/dishplay-scan-data/tls`). Il est gardé tant qu'il est
  valide (environ 13 mois, refait 7 jours avant l'échéance) : changer de Wi‑Fi ou allumer un VPN ne force plus
  un nouveau jumelage. `--new-certificate` en fait un nouveau ; chaque iPhone doit alors rescanner le QR ;
- un QR code (dans le terminal et sur `https://127.0.0.1:8765/`, page accessible seulement depuis le PC).
  Le navigateur du PC avertira que le certificat est auto-signé : c'est attendu, l'iPhone vérifie l'empreinte ;
- s'il empêchera la mise en veille du PC pendant un scan ou un calcul (voir plus bas) ;
- les calculs interrompus par l'arrêt précédent qu'il reprend.

`--forget-devices` oublie tous les iPhone jumelés (téléphone perdu ou prêté) : chacun doit être jumelé de nouveau.

## Plusieurs plats à la suite
Le calculateur fait **un calcul à la fois**. Quand vous touchez « Terminer » sur un plat puis scannez le suivant :
- le calcul du premier plat n'est jamais arrêté ;
- les demandes suivantes attendent leur tour et démarrent toutes seules, dans l'ordre ;
- le scan du plat suivant est accepté et ses vues sont gardées sur le PC, mais **son aperçu en direct ne démarre
  que lorsque le calculateur est libre** : pendant qu'un calcul final tourne, on scanne sans aperçu ;
- un calcul qui échoue (disque plein, mémoire, arrêt brutal) est signalé dans l'app et sur le PC, avec les
  détails dans `~/dishplay-scan-data/calculateur.log` ; les suivants continuent ; le plat se relance depuis l'app.

## Veille du PC
Personne ne touche le PC pendant qu'on scanne, et un calcul final dure un quart d'heure : avec ses réglages
habituels, un portable s'endort au milieu. Sous Windows (et sous Linux avec systemd, macOS), le calculateur
demande au système de rester éveillé tant qu'un scan ou un calcul est en cours, puis rend la main ; l'écran peut
s'éteindre. Non essayé sous Windows par le projet : si l'app affiche « injoignable » au milieu d'un calcul,
régler la mise en veille sur « jamais » (Paramètres › Système › Alimentation) et me le signaler.

## Diagnostic
```bash
backend/.venv/bin/python tools/doctor.py          # Windows : backend\.venv\Scripts\python.exe tools\doctor.py
```
Vérifie versions OpenCV/Open3D, RAM, adresse LAN, port libre, WSL, et exécute un auto-test **synthétique** de la
chaîne (preuve que les bibliothèques fonctionnent sur ce PC, jamais présenté comme un scan).

## Données
`~/dishplay-scan-data/sessions/<id>/` : `frames/` (JPEG originaux + JSON + profondeur LiDAR éventuelle),
`preview/vNNNNN.dpg` (toutes les versions intermédiaires), `final/` (PLY, GLB, USDZ, texture, rapport, manifeste),
`dishplay-scan.sqlite3` (index), `calculateur.log` (journal des pannes). Rejouer une session : voir `FIRST_TEST.md` § 9.

**Place sur le disque.** Un scan prend 100 à 300 Mo et rien n'est supprimé tout seul. Le calculateur prévient au
démarrage sous 5 Go libres, et refuse les nouvelles vues sous 500 Mo (l'app affiche alors la raison ; l'envoi
reprend quand la place est revenue). Chaque plat est un dossier de `dishplay-scan-data/sessions/`, nommé d'après
sa date ; avec l'app 1.7.1, le nom donné au plat sur l'iPhone est écrit dans son fichier `nom.txt`, et l'outil de
ménage l'affiche. Pour faire le ménage :
```bash
backend/.venv/bin/python tools/clean_sessions.py            # Windows : backend\.venv\Scripts\python.exe tools\clean_sessions.py
```
Sans option, il montre seulement ce qu'il supprimerait. `--apply` supprime : les vues et aperçus intermédiaires
des plats terminés depuis plus de 30 jours (`--days N` pour changer), et les scans sans modèle aussi anciens.
Les modèles (`final/`) ne sont supprimés qu'avec `--with-final`. Un plat en cours de calcul n'est jamais touché.

## Sécurité
HTTPS uniquement (certificat épinglé par l'app), jeton par appareil après jumelage, limite de taille des
requêtes (20 Mo par vue, 64 Ko pour les autres), noms de fichiers d'artefacts contrôlés. Après 8 codes de jumelage
faux de suite, le jumelage est bloqué 60 secondes. Ne pas exposer le port 8765 sur
Internet (pas de redirection de port sur la box). `--insecure-http` n'existe que pour des tests automatisés ;
l'app iOS refuse le HTTP.
