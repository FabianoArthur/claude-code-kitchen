# Kitchen.app — native menu-bar app. See docs/macos-app.md.
APP_DIR  ?= build
INSTALL  ?= $(HOME)/Applications

.PHONY: app install test screenshots clean

app:
	scripts/bundle.sh $(APP_DIR)

install: app
	mkdir -p "$(INSTALL)"
	rm -rf "$(INSTALL)/Kitchen.app"
	cp -R "$(APP_DIR)/Kitchen.app" "$(INSTALL)/Kitchen.app"
	@echo "Installed $(INSTALL)/Kitchen.app — open it with: open \"$(INSTALL)/Kitchen.app\""

test:
	swift test

screenshots: app
	scripts/screenshots.sh $(APP_DIR)/Kitchen.app ../docs/images

clean:
	rm -rf .build $(APP_DIR)
