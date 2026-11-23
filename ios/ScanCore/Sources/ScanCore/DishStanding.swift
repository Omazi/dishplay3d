import Foundation

/// What the dish screen offers for a dish that has no model yet.
public enum DishAction: Equatable, Sendable {
    /// Send the views still on the iPhone, then ask for the final model.
    case finish
    /// The final calculation failed: ask for it again.
    case restart
}

/// Where a dish without its model stands: from what the calculator answers about it (`SessionStatus`) and from
/// what the iPhone still holds. This is what "Mes plats" says about the dish, and whether it shows a button.
public enum DishStanding: Equatable, Sendable {
    /// The model exists on the calculator: the app fetches it.
    case ready
    /// The final calculation waits behind another dish and starts by itself. 1 = next.
    case queued(position: Int?)
    /// Being calculated, with a step that can be counted.
    case computing(step: String?, done: Int, total: Int)
    /// Being calculated, no count yet.
    case computingUncounted
    /// The final calculation failed, with the calculator's own sentence when it gave one.
    case failed(message: String?)
    /// A calculator without a queue is finishing another dish: this one has to be asked again afterwards.
    case waitingForOther
    /// Views taken for this dish never reached the calculator.
    case viewsToSend(Int)
    /// Everything was sent and nothing is running.
    case stopped

    public init(_ status: SessionStatus, pendingViews: Int) {
        if status.ready {
            self = .ready
        } else if status.queued == true {
            self = .queued(position: status.queuePosition)
        } else if (status.failed || status.state == "failed") && status.state != "finishing" {
            self = .failed(message: status.error)
        } else if let done = status.done, let total = status.total, total > 1 {
            self = .computing(step: status.step, done: done, total: total)
        } else if status.active && status.state == "finishing" {
            self = .computingUncounted
        } else if status.busyWithOther && status.queued == nil {
            self = .waitingForOther
        } else if pendingViews > 0 {
            self = .viewsToSend(pendingViews)
        } else {
            self = .stopped
        }
    }

    /// The button to show, nil when there is nothing for the person to do.
    public var action: DishAction? {
        switch self {
        case .viewsToSend, .stopped: return .finish
        case .failed: return .restart
        case .ready, .queued, .computing, .computingUncounted, .waitingForOther: return nil
        }
    }

    /// 0...1 while a step can be counted.
    public var fraction: Double? {
        guard case .computing(_, let done, let total) = self, total > 0 else { return nil }
        return min(1, max(0, Double(done) / Double(total)))
    }

    /// One line, in French, for the dish card and the dish screen.
    public var text: String {
        switch self {
        case .ready:
            return "Modèle prêt, réception en cours…"
        case .queued(let position):
            return QueueWording.waiting(position)
        case .computing(let step, let done, let total):
            return "\(DishStanding.stepName(step)) · \(done)/\(total)"
        case .computingUncounted:
            return "Calcul du modèle en cours…"
        case .failed(let message):
            return message ?? "Le calcul du modèle n’a pas abouti."
        case .waitingForOther:
            return "En attente : un autre plat est en cours de calcul"
        case .viewsToSend(let count):
            return count == 1 ? "1 vue à envoyer" : "\(count) vues à envoyer"
        case .stopped:
            return "Calcul arrêté"
        }
    }

    private static func stepName(_ step: String?) -> String {
        switch step ?? "" {
        case "poses": return "Recalage des vues"
        case "neural": return "Rendu neuronal"
        default: return "Calcul du modèle"
        }
    }
}

/// How the app says that a dish waits its turn on the calculator.
public enum QueueWording {
    /// "2e dans la file"; nil when the place is not known.
    public static func place(_ position: Int?) -> String? {
        guard let position, position >= 1 else { return nil }
        return position == 1 ? "1er dans la file" : "\(position)e dans la file"
    }

    /// "En attente, 2e dans la file".
    public static func waiting(_ position: Int?) -> String {
        guard let words = place(position) else { return "En attente : un autre plat est en cours de calcul" }
        return "En attente, \(words)"
    }
}
