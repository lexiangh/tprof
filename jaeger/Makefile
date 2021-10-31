PROJECT_ROOT=github.com/jaegertracing/jaeger
STORAGE_PKGS = ./plugin/storage/integration/...

# all .go files that are not auto-generated and should be auto-formatted and linted.
ALL_SRC := $(shell find . -name '*.go' \
				   -not -name 'doc.go' \
				   -not -name '_*' \
				   -not -name '.*' \
				   -not -name 'gen_assets.go' \
				   -not -name 'mocks*' \
				   -not -name 'model.pb.go' \
				   -not -name 'model_test.pb.go' \
				   -not -name 'storage_test.pb.go' \
				   -not -path './examples/*' \
				   -not -path './vendor/*' \
				   -not -path '*/mocks/*' \
				   -not -path '*/*-gen/*' \
				   -not -path '*/thrift-0.9.2/*' \
				   -type f | \
				sort)

# ALL_PKGS is used with 'go cover' and 'golint'
ALL_PKGS := $(shell go list $(sort $(dir $(ALL_SRC))))

RACE=-race
GOTEST=go test -v $(RACE)
GOLINT=golint
GOVET=go vet
GOFMT=gofmt
GOSEC=gosec -quiet -exclude=G104,G107
STATICCHECK=staticcheck
FMT_LOG=fmt.log
LINT_LOG=lint.log
IMPORT_LOG=import.log

GIT_SHA=$(shell git rev-parse HEAD)
GIT_CLOSEST_TAG=$(shell git describe --abbrev=0 --tags)
DATE=$(shell date -u +'%Y-%m-%dT%H:%M:%SZ')
BUILD_INFO_IMPORT_PATH=github.com/jaegertracing/jaeger/pkg/version
BUILD_INFO=-ldflags "-X $(BUILD_INFO_IMPORT_PATH).commitSHA=$(GIT_SHA) -X $(BUILD_INFO_IMPORT_PATH).latestVersion=$(GIT_CLOSEST_TAG) -X $(BUILD_INFO_IMPORT_PATH).date=$(DATE)"

SED=sed
THRIFT_VER=0.9.3
THRIFT_IMG=thrift:$(THRIFT_VER)
THRIFT=docker run --rm -u ${shell id -u} -v "${PWD}:/data" $(THRIFT_IMG) thrift
THRIFT_GO_ARGS=thrift_import="github.com/apache/thrift/lib/go/thrift"
THRIFT_GEN=$(shell which thrift-gen)
THRIFT_GEN_DIR=thrift-gen

SWAGGER_VER=0.12.0
SWAGGER_IMAGE=quay.io/goswagger/swagger:$(SWAGGER_VER)
SWAGGER=docker run --rm -it -u ${shell id -u} -v "${PWD}:/go/src/${PROJECT_ROOT}" -w /go/src/${PROJECT_ROOT} $(SWAGGER_IMAGE)
SWAGGER_GEN_DIR=swagger-gen

COLOR_PASS=$(shell printf "\033[32mPASS\033[0m")
COLOR_FAIL=$(shell printf "\033[31mFAIL\033[0m")
COLORIZE=$(SED) ''/PASS/s//$(COLOR_PASS)/'' | $(SED) ''/FAIL/s//$(COLOR_FAIL)/''
DOCKER_NAMESPACE?=jaegertracing
DOCKER_TAG?=latest

MOCKERY=mockery

.DEFAULT_GOAL := test-and-lint

.PHONY: test-and-lint
test-and-lint: test fmt lint

# TODO: no files actually use this right now
.PHONY: go-gen
go-gen:
	@echo skipping go generate ./...

.PHONY: md-to-godoc-gen
md-to-godoc-gen:
	find . -name README.md -not -path "./vendor/*" -not -path "./_site/*" -not -path "./idl/*" \
		| grep -v '^./README.md' \
		| xargs -I% md-to-godoc -license -licenseFile LICENSE -input=%

.PHONY: clean
clean:
	rm -rf cover.out .cover/ cover.html lint.log fmt.log

.PHONY: test
test: go-gen
	bash -c "set -e; set -o pipefail; $(GOTEST) ./... | $(COLORIZE)"

.PHONY: all-in-one-integration-test
all-in-one-integration-test: go-gen
	$(GOTEST) -tags=integration ./cmd/all-in-one/...

.PHONY: storage-integration-test
storage-integration-test: go-gen
	# Expire tests results for storage integration tests since the environment might change
	# even though the code remains the same.
	go clean -testcache
	bash -c "set -e; set -o pipefail; $(GOTEST) $(STORAGE_PKGS) | $(COLORIZE)"

.PHONE: test-compile-es-scripts
test-compile-es-scripts:
	docker run --rm -it -v ${PWD}:/tmp/jaeger python:3-alpine /usr/local/bin/python -m py_compile /tmp/jaeger/plugin/storage/es/esRollover.py
	docker run --rm -it -v ${PWD}:/tmp/jaeger python:3-alpine /usr/local/bin/python -m py_compile /tmp/jaeger/plugin/storage/es/esCleaner.py

.PHONY: index-cleaner-integration-test
index-cleaner-integration-test: docker-images-elastic
	# Expire tests results for storage integration tests since the environment might change
	# even though the code remains the same.
	go clean -testcache
	bash -c "set -e; set -o pipefail; $(GOTEST) -tags index_cleaner $(STORAGE_PKGS) | $(COLORIZE)"

.PHONY: token-propagation-integration-test
token-propagation-integration-test:
	go clean -testcache
	bash -c "set -e; set -o pipefail; $(GOTEST) -tags token_propagation -run TestBearTokenPropagation $(STORAGE_PKGS) | $(COLORIZE)"

all-pkgs:
	@echo $(ALL_PKGS) | tr ' ' '\n' | sort

all-srcs:
	@echo $(ALL_SRC) | tr ' ' '\n' | sort

.PHONY: cover
cover: nocover
	@echo pre-compiling tests
	@time go test -i $(ALL_PKGS)
	@./scripts/cover.sh $(shell go list ./...)
	grep -E -v 'model.pb.*.go' cover.out > cover-nogen.out
	mv cover-nogen.out cover.out
	go tool cover -html=cover.out -o cover.html

.PHONY: nocover
nocover:
	@echo Verifying that all packages have test files to count in coverage
	@scripts/check-test-files.sh $(subst github.com/jaegertracing/jaeger/,./,$(ALL_PKGS))

.PHONY: fmt
fmt:
	./scripts/import-order-cleanup.sh inplace
	@echo Running go fmt on ALL_SRC ...
	@$(GOFMT) -e -s -l -w $(ALL_SRC)
	./scripts/updateLicenses.sh

.PHONY: lint-gosec
lint-gosec:
	time $(GOSEC) ./...

.PHONY: lint-staticcheck
lint-staticcheck:
	@echo Running staticcheck...
	@cat /dev/null > $(LINT_LOG)
	@time $(STATICCHECK) ./... \
		| grep -v \
			-e model/model.pb.go \
			-e thrift-gen/ \
		>> $(LINT_LOG) || true
	@[ ! -s "$(LINT_LOG)" ] || (echo "Detected staticcheck failures:" | cat - $(LINT_LOG) && false)

.PHONY: lint
lint: lint-staticcheck lint-gosec
	$(GOVET) ./...
	$(MAKE) go-lint
	@echo Running go fmt on ALL_SRC ...
	@$(GOFMT) -e -s -l $(ALL_SRC) > $(FMT_LOG)
	@./scripts/updateLicenses.sh >> $(FMT_LOG)
	@./scripts/import-order-cleanup.sh stdout > $(IMPORT_LOG)
	@[ ! -s "$(FMT_LOG)" -a ! -s "$(IMPORT_LOG)" ] || (echo "Go fmt, license check, or import ordering failures, run 'make fmt'" | cat - $(FMT_LOG) && false)

.PHONY: go-lint
go-lint:
	@cat /dev/null > $(LINT_LOG)
	@echo Running go lint...
	@$(GOLINT) $(ALL_PKGS) \
		| grep -v _nolint.go \
		>> $(LINT_LOG) || true;
	@[ ! -s "$(LINT_LOG)" ] || (echo "Lint Failures" | cat - $(LINT_LOG) && false)

.PHONY: install-glide
install-glide:
	@echo "WARNING: Jaeger has migrated to dep, install-glide is now deprecated" 1>&2
	$(MAKE) install

.PHONY: install
install:
	@which dep > /dev/null || curl https://raw.githubusercontent.com/golang/dep/master/install.sh | sh
	dep ensure -vendor-only

.PHONE: elasticsearch-mappings
elasticsearch-mappings:
	esc -pkg mappings -o plugin/storage/es/mappings/gen_assets.go -ignore assets -prefix plugin/storage/es/mappings plugin/storage/es/mappings

.PHONY: build-examples
build-examples:
	esc -pkg frontend -o examples/hotrod/services/frontend/gen_assets.go  -prefix examples/hotrod/services/frontend/web_assets examples/hotrod/services/frontend/web_assets
	CGO_ENABLED=0 installsuffix=cgo go build -o ./examples/hotrod/hotrod-$(GOOS) ./examples/hotrod/main.go

.PHONE: docker-hotrod
docker-hotrod:
	GOOS=linux $(MAKE) build-examples
	docker build -t $(DOCKER_NAMESPACE)/example-hotrod:${DOCKER_TAG} ./examples/hotrod

.PHONY: build-ui
build-ui:
	cd jaeger-ui && yarn install --frozen-lockfile && cd packages/jaeger-ui && yarn build
	esc -pkg assets -o cmd/query/app/ui/actual/gen_assets.go -prefix jaeger-ui/packages/jaeger-ui/build jaeger-ui/packages/jaeger-ui/build
	esc -pkg assets -o cmd/query/app/ui/placeholder/gen_assets.go -prefix cmd/query/app/ui/placeholder/public cmd/query/app/ui/placeholder/public

.PHONY: build-all-in-one-linux
build-all-in-one-linux: build-ui
	GOOS=linux $(MAKE) build-all-in-one

.PHONY: build-all-in-one
build-all-in-one: elasticsearch-mappings
	CGO_ENABLED=0 installsuffix=cgo go build -tags ui -o ./cmd/all-in-one/all-in-one-$(GOOS) $(BUILD_INFO) ./cmd/all-in-one/main.go

.PHONY: build-agent
build-agent:
	CGO_ENABLED=0 installsuffix=cgo go build -o ./cmd/agent/agent-$(GOOS) $(BUILD_INFO) ./cmd/agent/main.go

.PHONY: build-query
build-query:
	CGO_ENABLED=0 installsuffix=cgo go build -tags ui -o ./cmd/query/query-$(GOOS) $(BUILD_INFO) ./cmd/query/main.go

.PHONY: build-collector
build-collector: elasticsearch-mappings
	CGO_ENABLED=0 installsuffix=cgo go build -o ./cmd/collector/collector-$(GOOS) $(BUILD_INFO) ./cmd/collector/main.go

.PHONY: build-ingester
build-ingester:
	CGO_ENABLED=0 installsuffix=cgo go build -o ./cmd/ingester/ingester-$(GOOS) $(BUILD_INFO) ./cmd/ingester/main.go

.PHONY: docker
docker: build-ui build-binaries-linux docker-images-only

.PHONY: build-binaries-linux
build-binaries-linux:
	GOOS=linux $(MAKE) build-platform-binaries

.PHONY: build-binaries-windows
build-binaries-windows:
	GOOS=windows $(MAKE) build-platform-binaries

.PHONY: build-binaries-darwin
build-binaries-darwin:
	GOOS=darwin $(MAKE) build-platform-binaries

.PHONY: build-platform-binaries
build-platform-binaries: build-agent build-collector build-query build-ingester build-all-in-one build-examples

.PHONY: build-all-platforms
build-all-platforms: build-binaries-linux build-binaries-windows build-binaries-darwin

.PHONY: docker-images-cassandra
docker-images-cassandra:
	docker build -t $(DOCKER_NAMESPACE)/jaeger-cassandra-schema:${DOCKER_TAG} plugin/storage/cassandra/
	@echo "Finished building jaeger-cassandra-schema =============="

.PHONY: docker-images-elastic
docker-images-elastic:
	docker build -t $(DOCKER_NAMESPACE)/jaeger-es-index-cleaner:${DOCKER_TAG} plugin/storage/es
	docker build -t $(DOCKER_NAMESPACE)/jaeger-es-rollover:${DOCKER_TAG} plugin/storage/es -f plugin/storage/es/Dockerfile.rollover
	@echo "Finished building jaeger-es-indices-clean =============="

.PHONY: docker-images-jaeger-backend
docker-images-jaeger-backend:
	for component in agent collector query ingester ; do \
		docker build -t $(DOCKER_NAMESPACE)/jaeger-$$component:${DOCKER_TAG} cmd/$$component ; \
		echo "Finished building $$component ==============" ; \
	done

.PHONY: docker-images-only
docker-images-only: docker-images-cassandra docker-images-elastic docker-images-jaeger-backend

.PHONY: docker-push
docker-push:
	@while [ -z "$$CONFIRM" ]; do \
		read -r -p "Do you really want to push images to repository \"${DOCKER_NAMESPACE}\"? [y/N] " CONFIRM; \
	done ; \
	if [ $$CONFIRM != "y" ] && [ $$CONFIRM != "Y" ]; then \
		echo "Exiting." ; exit 1 ; \
	fi
	for component in agent cassandra-schema es-index-cleaner es-rollover collector query ingester example-hotrod; do \
		docker push $(DOCKER_NAMESPACE)/jaeger-$$component ; \
	done

.PHONY: build-crossdock-linux
build-crossdock-linux:
	CGO_ENABLED=0 GOOS=linux installsuffix=cgo go build -o ./crossdock/crossdock-linux ./crossdock/main.go

include crossdock/rules.mk

# Crossdock tests do not require fully functioning UI, so we skip it to speed up the build.
.PHONY: build-crossdock-ui-placeholder
build-crossdock-ui-placeholder:
	mkdir -p cmd/query/app/ui/actual
	[ -e cmd/query/app/ui/actual/gen_assets.go ] || cp cmd/query/app/ui/placeholder/gen_assets.go cmd/query/app/ui/actual/gen_assets.go

.PHONY: build-crossdock
build-crossdock: build-crossdock-ui-placeholder build-binaries-linux build-crossdock-linux docker-images-cassandra docker-images-jaeger-backend
	docker build -t $(DOCKER_NAMESPACE)/test-driver:${DOCKER_TAG} crossdock/
	@echo "Finished building test-driver ==============" ; \

.PHONY: build-and-run-crossdock
build-and-run-crossdock: build-crossdock
	make crossdock

.PHONY: build-crossdock-fresh
build-crossdock-fresh: build-crossdock-linux
	make crossdock-fresh

.PHONY: changelog
changelog:
	@echo "Set env variable OAUTH_TOKEN before invoking, https://github.com/settings/tokens/new?description=GitHub%20Changelog%20Generator%20token"
	docker run --rm  -v "${PWD}:/app" pavolloffay/gch:latest --oauth-token ${OAUTH_TOKEN} --owner jaegertracing --repo jaeger

.PHONY: install-tools
install-tools:
	go get -u github.com/wadey/gocovmerge
	go get -u golang.org/x/tools/cmd/cover
	go get -u golang.org/x/lint/golint
	go get -u github.com/sectioneight/md-to-godoc
	go get -u github.com/mjibson/esc
	go install ./vendor/github.com/securego/gosec/cmd/gosec/
	go install ./vendor/honnef.co/go/tools/cmd/staticcheck/

.PHONY: install-ci
install-ci: install install-tools

.PHONY: test-ci
test-ci: build-examples lint cover

# TODO at the moment we're not generating tchan_*.go files
.PHONY: thrift
thrift: idl/thrift/jaeger.thrift thrift-image
	[ -d $(THRIFT_GEN_DIR) ] || mkdir $(THRIFT_GEN_DIR)
	$(THRIFT) -o /data --gen go:$(THRIFT_GO_ARGS) --out /data/$(THRIFT_GEN_DIR) /data/idl/thrift/agent.thrift
#	TODO sed is GNU and BSD compatible
	sed -i.bak 's|"zipkincore"|"$(PROJECT_ROOT)/thrift-gen/zipkincore"|g' $(THRIFT_GEN_DIR)/agent/*.go
	sed -i.bak 's|"jaeger"|"$(PROJECT_ROOT)/thrift-gen/jaeger"|g' $(THRIFT_GEN_DIR)/agent/*.go
	$(THRIFT) -o /data --gen go:$(THRIFT_GO_ARGS) --out /data/$(THRIFT_GEN_DIR) /data/idl/thrift/jaeger.thrift
	$(THRIFT) -o /data --gen go:$(THRIFT_GO_ARGS) --out /data/$(THRIFT_GEN_DIR) /data/idl/thrift/sampling.thrift
	$(THRIFT) -o /data --gen go:$(THRIFT_GO_ARGS) --out /data/$(THRIFT_GEN_DIR) /data/idl/thrift/baggage.thrift
	$(THRIFT) -o /data --gen go:$(THRIFT_GO_ARGS) --out /data/$(THRIFT_GEN_DIR) /data/idl/thrift/zipkincore.thrift
	@echo Generate TChannel-Thrift bindings
	$(THRIFT_GEN) --inputFile idl/thrift/jaeger.thrift --outputDir $(THRIFT_GEN_DIR)
	$(THRIFT_GEN) --inputFile idl/thrift/sampling.thrift --outputDir $(THRIFT_GEN_DIR)
	$(THRIFT_GEN) --inputFile idl/thrift/baggage.thrift --outputDir $(THRIFT_GEN_DIR)
	$(THRIFT_GEN) --inputFile idl/thrift/zipkincore.thrift --outputDir $(THRIFT_GEN_DIR)
	rm -rf thrift-gen/*/*-remote thrift-gen/*/*.bak

idl/thrift/jaeger.thrift:
	$(MAKE) idl-submodule

.PHONY: idl-submodule
idl-submodule:
	git submodule init
	git submodule update

.PHONY: thrift-image
thrift-image:
	$(THRIFT) -version

.PHONY: generate-zipkin-swagger
generate-zipkin-swagger: idl-submodule
	$(SWAGGER) generate server -f ./idl/swagger/zipkin2-api.yaml -t $(SWAGGER_GEN_DIR) -O PostSpans --exclude-main
	rm $(SWAGGER_GEN_DIR)/restapi/operations/post_spans_urlbuilder.go $(SWAGGER_GEN_DIR)/restapi/server.go $(SWAGGER_GEN_DIR)/restapi/configure_zipkin.go $(SWAGGER_GEN_DIR)/models/trace.go $(SWAGGER_GEN_DIR)/models/list_of_traces.go $(SWAGGER_GEN_DIR)/models/dependency_link.go

.PHONY: install-mockery
install-mockery:
	go get -u github.com/vektra/mockery/.../

.PHONY: generate-mocks
generate-mocks: install-mockery
	$(MOCKERY) -all -dir ./pkg/es/ -output ./pkg/es/mocks && rm pkg/es/mocks/ClientBuilder.go

.PHONY: echo-version
echo-version:
	@echo $(GIT_CLOSEST_TAG)

PROTOC := protoc
PROTO_INCLUDES := \
	-I model/proto \
	-I idl/proto \
	-I vendor/github.com/grpc-ecosystem/grpc-gateway \
	-I vendor/github.com/gogo/googleapis \
	-I vendor/github.com/gogo/protobuf/protobuf \
	-I vendor/github.com/gogo/protobuf
# Remapping of std types to gogo types (must not contain spaces)
PROTO_GOGO_MAPPINGS := $(shell echo \
		Mgoogle/protobuf/descriptor.proto=github.com/gogo/protobuf/types, \
		Mgoogle/protobuf/timestamp.proto=github.com/gogo/protobuf/types, \
		Mgoogle/protobuf/duration.proto=github.com/gogo/protobuf/types, \
		Mgoogle/protobuf/empty.proto=github.com/gogo/protobuf/types, \
		Mgoogle/api/annotations.proto=github.com/gogo/googleapis/google/api, \
		Mmodel.proto=github.com/jaegertracing/jaeger/model \
	| sed 's/ //g')


.PHONY: proto
proto:
	# Generate gogo, gRPC-Gateway, swagger, go-validators, gRPC-storage-plugin output.
	#
	# -I declares import folders, in order of importance
	# This is how proto resolves the protofile imports.
	# It will check for the protofile relative to each of these
	# folders and use the first one it finds.
	#
	# --gogo_out generates GoGo Protobuf output with gRPC plugin enabled.
	# --grpc-gateway_out generates gRPC-Gateway output.
	# --swagger_out generates an OpenAPI 2.0 specification for our gRPC-Gateway endpoints.
	# --govalidators_out generates Go validation files for our messages types, if specified.
	#
	# The lines starting with Mgoogle/... are proto import replacements,
	# which cause the generated file to import the specified packages
	# instead of the go_package's declared by the imported protof files.
	#
	# $$GOPATH/src is the output directory. It is relative to the GOPATH/src directory
	# since we've specified a go_package option relative to that directory.
	#
	# model/proto/jaeger.proto is the location of the protofile we use.
	#
	# TODO use Docker container instead of installed protoc
	# (https://medium.com/@linchenon/generate-grpc-and-protobuf-libraries-with-containers-c15ba4e4f3ad)
	#
	$(PROTOC) \
		$(PROTO_INCLUDES) \
		--gogo_out=plugins=grpc,$(PROTO_GOGO_MAPPINGS):$(PWD)/model/ \
		model/proto/model.proto

	$(PROTOC) \
		$(PROTO_INCLUDES) \
		--gogo_out=plugins=grpc,$(PROTO_GOGO_MAPPINGS):$(PWD)/proto-gen/ \
		model/proto/api_v2/*.proto
		### grpc-gateway generates 'query.pb.gw.go' that does not respect (gogoproto.customname) = "TraceID"
		### --grpc-gateway_out=$(PROTO_GOGO_MAPPINGS):$(PWD)/proto-gen/ \
		### --swagger_out=allow_merge=true:$(PWD)/proto-gen/openapi/ \

	$(PROTOC) \
		$(PROTO_INCLUDES) \
		-I plugin/storage/grpc/proto \
		--gogo_out=plugins=grpc,$(PROTO_GOGO_MAPPINGS):$(PWD)/proto-gen/storage_v1 \
		plugin/storage/grpc/proto/storage.proto

	$(PROTOC) \
		-I model/proto \
		--go_out=$(PWD)/model/prototest/ \
		model/proto/model_test.proto

	$(PROTOC) \
		-I plugin/storage/grpc/proto \
		--go_out=$(PWD)/plugin/storage/grpc/proto/storageprototest/ \
		plugin/storage/grpc/proto/storage_test.proto

	$(PROTOC) \
		$(PROTO_INCLUDES) \
		--gogo_out=plugins=grpc,$(PROTO_GOGO_MAPPINGS):$(PWD)/proto-gen/zipkin \
		idl/proto/zipkin.proto


.PHONY: proto-install
proto-install:
	go get -u github.com/golang/glog
	go install \
		./vendor/github.com/golang/protobuf/protoc-gen-go \
		./vendor/github.com/gogo/protobuf/protoc-gen-gogo \
		./vendor/github.com/grpc-ecosystem/grpc-gateway/protoc-gen-grpc-gateway \
		./vendor/github.com/grpc-ecosystem/grpc-gateway/protoc-gen-swagger
		# ./vendor/github.com/mwitkow/go-proto-validators/protoc-gen-govalidators
