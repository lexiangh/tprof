// Copyright (c) 2019 The Jaeger Authors.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package flags

import (
	"context"
	"flag"
	"net"
	"net/http"
	"net/http/pprof"
	"strconv"

	"github.com/spf13/viper"
	"go.uber.org/zap"

	"github.com/jaegertracing/jaeger/pkg/healthcheck"
	"github.com/jaegertracing/jaeger/pkg/recoveryhandler"
	"github.com/jaegertracing/jaeger/pkg/version"
)

const (
	adminHTTPPort       = "admin-http-port"
	healthCheckHTTPPort = "health-check-http-port"
)

// AdminServer runs an HTTP server with admin endpoints, such as healthcheck at /, /metrics, etc.
type AdminServer struct {
	logger    *zap.Logger
	adminPort int

	hc *healthcheck.HealthCheck

	mux    *http.ServeMux
	server *http.Server
}

// NewAdminServer creates a new admin server.
func NewAdminServer(defaultPort int) *AdminServer {
	return &AdminServer{
		adminPort: defaultPort,
		logger:    zap.NewNop(),
		hc:        healthcheck.New(),
		mux:       http.NewServeMux(),
	}
}

// HC returns the reference to HeathCheck.
func (s *AdminServer) HC() *healthcheck.HealthCheck {
	return s.hc
}

// setLogger initializes logger.
func (s *AdminServer) setLogger(logger *zap.Logger) {
	s.logger = logger
	s.hc.SetLogger(logger)
}

// AddFlags registers CLI flags.
func (s *AdminServer) AddFlags(flagSet *flag.FlagSet) {
	flagSet.Int(healthCheckHTTPPort, 0, "(deprecated) see --"+adminHTTPPort)
	flagSet.Int(adminHTTPPort, s.adminPort, "The http port for the admin server, including health check, /metrics, etc.")
}

// InitFromViper initializes the server with properties retrieved from Viper.
func (s *AdminServer) initFromViper(v *viper.Viper, logger *zap.Logger) {
	s.setLogger(logger)
	s.adminPort = v.GetInt(adminHTTPPort)
	if v := v.GetInt(healthCheckHTTPPort); v != 0 {
		logger.Sugar().Warnf("Using deprecated flag %s, please upgrade to %s", healthCheckHTTPPort, adminHTTPPort)
		s.adminPort = v
	}
}

// Handle adds a new handler to the admin server.
func (s *AdminServer) Handle(path string, handler http.Handler) {
	s.mux.Handle(path, handler)
}

// Serve starts HTTP server.
func (s *AdminServer) Serve() error {
	portStr := ":" + strconv.Itoa(s.adminPort)
	l, err := net.Listen("tcp", portStr)
	if err != nil {
		s.logger.Error("Admin server failed to listen", zap.Error(err))
		return err
	}
	s.serveWithListener(l)
	s.logger.Info(
		"Admin server started",
		zap.Int("http-port", s.adminPort),
		zap.Stringer("health-status", s.hc.Get()))
	return nil
}

func (s *AdminServer) serveWithListener(l net.Listener) {
	s.logger.Info("Mounting health check on admin server", zap.String("route", "/"))
	s.mux.Handle("/", s.hc.Handler())
	version.RegisterHandler(s.mux, s.logger)
	s.registerPprofHandlers()
	recoveryHandler := recoveryhandler.NewRecoveryHandler(s.logger, true)
	s.server = &http.Server{Handler: recoveryHandler(s.mux)}
	s.logger.Info("Starting admin HTTP server", zap.Int("http-port", s.adminPort))
	go func() {
		switch err := s.server.Serve(l); err {
		case nil, http.ErrServerClosed:
			// normal exit, nothing to do
		default:
			s.logger.Error("failed to serve", zap.Error(err))
			s.hc.Set(healthcheck.Broken)
		}
	}()
}

func (s *AdminServer) registerPprofHandlers() {
	s.mux.HandleFunc("/debug/pprof/", pprof.Index)
	s.mux.HandleFunc("/debug/pprof/cmdline", pprof.Cmdline)
	s.mux.HandleFunc("/debug/pprof/profile", pprof.Profile)
	s.mux.HandleFunc("/debug/pprof/symbol", pprof.Symbol)
	s.mux.HandleFunc("/debug/pprof/trace", pprof.Trace)
	s.mux.Handle("/debug/pprof/goroutine", pprof.Handler("goroutine"))
	s.mux.Handle("/debug/pprof/heap", pprof.Handler("heap"))
	s.mux.Handle("/debug/pprof/threadcreate", pprof.Handler("threadcreate"))
	s.mux.Handle("/debug/pprof/block", pprof.Handler("block"))
}

// Close stops the HTTP server
func (s *AdminServer) Close() error {
	return s.server.Shutdown(context.Background())
}
