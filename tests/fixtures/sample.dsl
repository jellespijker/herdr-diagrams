workspace "Diagrams" {
    model {
        user = person "Developer"
        sys = softwareSystem "herdr-diagrams" {
            cli = container "herdr-diagram CLI" "Python"
            viewer = container "Viewer pane" "Python"
        }
        agent = softwareSystem "Coding agent"
        user -> agent "Prompts"
        agent -> cli "Queues diagrams"
        cli -> viewer "Spool files"
        user -> viewer "Looks at"
    }
    views {
        systemContext sys {
            include *
            autolayout lr
        }
        container sys {
            include *
            autolayout lr
        }
    }
}
