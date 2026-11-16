# Skills installés dans ce projet

Copiés tels quels depuis des dépôts publics (lus avant installation), à la révision indiquée.
Ils se chargent à la demande dans les sessions Claude Code ouvertes sur ce dépôt.

| Skill | Dépôt | Révision | Licence | Usage |
|---|---|---|---|---|
| swiftui-pro | twostraws/SwiftUI-Agent-Skill | f2920b6 | MIT | revue du code SwiftUI (app iPhone) |
| liquid-glass, animation-patterns, typography, sf-symbols, ux-writing, design-system, ui-review, accessibility-audit, swiftui-debugging | rshankras/claude-code-apple-skills | f958982 | MIT | design et qualité de l'app iPhone |
| frontend-design, webapp-testing | anthropics/skills | e4bb5d9 | Apache-2.0 | design et tests du site web |
| apple-design, animate, gestures, review-animations | emilkowalski/skills | 64eb3de | MIT | animations et gestes du site web |
| brainstorming, writing-plans, executing-plans, test-driven-development, systematic-debugging, verification-before-completion | obra/superpowers | 22f0b46 | MIT | méthode de travail |

## Choix faits à l'installation

- **dickwu/apple-design-skill : non installé.** Le dépôt n'a pas de licence et son contenu principal est une copie
  du texte des Human Interface Guidelines d'Apple (1,5 Mo), qui appartient à Apple. Les mêmes sujets sont couverts par
  swiftui-pro (références design et accessibilité), ui-review, liquid-glass et accessibility-audit.
- **rshankras** : 9 skills retenus sur 184 (ceux qui servent à cette app) ; **anthropics/skills** : 2 sur 19.
- **obra/superpowers** : les skills seulement. Ni le script de démarrage de session (qui modifie le comportement de
  toutes les sessions), ni le petit serveur web de « brainstorming » n'ont été copiés.
