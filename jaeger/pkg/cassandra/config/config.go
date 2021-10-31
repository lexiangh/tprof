// Copyright (c) 2019 The Jaeger Authors.
// Copyright (c) 2017 Uber Technologies, Inc.
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

package config

import (
	"crypto/tls"
	"fmt"
	"time"

	"github.com/gocql/gocql"

	"github.com/jaegertracing/jaeger/pkg/cassandra"
	gocqlw "github.com/jaegertracing/jaeger/pkg/cassandra/gocql"
)

// Configuration describes the configuration properties needed to connect to a Cassandra cluster
type Configuration struct {
	Servers              []string      `validate:"nonzero"`
	Keyspace             string        `validate:"nonzero"`
	LocalDC              string        `yaml:"local_dc"`
	ConnectionsPerHost   int           `validate:"min=1" yaml:"connections_per_host"`
	Timeout              time.Duration `validate:"min=500"`
	ConnectTimeout       time.Duration `yaml:"connect_timeout"`
	ReconnectInterval    time.Duration `validate:"min=500" yaml:"reconnect_interval"`
	SocketKeepAlive      time.Duration `validate:"min=0" yaml:"socket_keep_alive"`
	MaxRetryAttempts     int           `validate:"min=0" yaml:"max_retry_attempt"`
	ProtoVersion         int           `yaml:"proto_version"`
	Consistency          string        `yaml:"consistency"`
	DisableCompression   bool          `yaml:"disable-compression"`
	Port                 int           `yaml:"port"`
	Authenticator        Authenticator `yaml:"authenticator"`
	DisableAutoDiscovery bool          `yaml:"disable_auto_discovery"`
	EnableDependenciesV2 bool          `yaml:"enable_dependencies_v2"`
	TLS                  TLS
}

// Authenticator holds the authentication properties needed to connect to a Cassandra cluster
type Authenticator struct {
	Basic BasicAuthenticator `yaml:"basic"`
	// TODO: add more auth types
}

// BasicAuthenticator holds the username and password for a password authenticator for a Cassandra cluster
type BasicAuthenticator struct {
	Username string `yaml:"username"`
	Password string `yaml:"password"`
}

// TLS Config
type TLS struct {
	Enabled                bool
	ServerName             string
	CertPath               string
	KeyPath                string
	CaPath                 string
	EnableHostVerification bool
}

// ApplyDefaults copies settings from source unless its own value is non-zero.
func (c *Configuration) ApplyDefaults(source *Configuration) {
	if c.ConnectionsPerHost == 0 {
		c.ConnectionsPerHost = source.ConnectionsPerHost
	}
	if c.MaxRetryAttempts == 0 {
		c.MaxRetryAttempts = source.MaxRetryAttempts
	}
	if c.Timeout == 0 {
		c.Timeout = source.Timeout
	}
	if c.ReconnectInterval == 0 {
		c.ReconnectInterval = source.ReconnectInterval
	}
	if c.Port == 0 {
		c.Port = source.Port
	}
	if c.Keyspace == "" {
		c.Keyspace = source.Keyspace
	}
	if c.ProtoVersion == 0 {
		c.ProtoVersion = source.ProtoVersion
	}
	if c.SocketKeepAlive == 0 {
		c.SocketKeepAlive = source.SocketKeepAlive
	}
}

// SessionBuilder creates new cassandra.Session
type SessionBuilder interface {
	NewSession() (cassandra.Session, error)
}

// NewSession creates a new Cassandra session
func (c *Configuration) NewSession() (cassandra.Session, error) {
	cluster := c.NewCluster()
	session, err := cluster.CreateSession()
	if err != nil {
		return nil, err
	}
	return gocqlw.WrapCQLSession(session), nil
}

// NewCluster creates a new gocql cluster from the configuration
func (c *Configuration) NewCluster() *gocql.ClusterConfig {
	cluster := gocql.NewCluster(c.Servers...)
	cluster.Keyspace = c.Keyspace
	cluster.NumConns = c.ConnectionsPerHost
	cluster.Timeout = c.Timeout
	cluster.ConnectTimeout = c.ConnectTimeout
	cluster.ReconnectInterval = c.ReconnectInterval
	cluster.SocketKeepalive = c.SocketKeepAlive
	if c.ProtoVersion > 0 {
		cluster.ProtoVersion = c.ProtoVersion
	}
	if c.MaxRetryAttempts > 1 {
		cluster.RetryPolicy = &gocql.SimpleRetryPolicy{NumRetries: c.MaxRetryAttempts - 1}
	}
	if c.Port != 0 {
		cluster.Port = c.Port
	}

	if !c.DisableCompression {
		cluster.Compressor = gocql.SnappyCompressor{}
	}

	if c.Consistency == "" {
		cluster.Consistency = gocql.LocalOne
	} else {
		cluster.Consistency = gocql.ParseConsistency(c.Consistency)
	}

	fallbackHostSelectionPolicy := gocql.RoundRobinHostPolicy()
	if c.LocalDC != "" {
		fallbackHostSelectionPolicy = gocql.DCAwareRoundRobinPolicy(c.LocalDC)
	}
	cluster.PoolConfig.HostSelectionPolicy = gocql.TokenAwareHostPolicy(fallbackHostSelectionPolicy, gocql.ShuffleReplicas())

	if c.Authenticator.Basic.Username != "" && c.Authenticator.Basic.Password != "" {
		cluster.Authenticator = gocql.PasswordAuthenticator{
			Username: c.Authenticator.Basic.Username,
			Password: c.Authenticator.Basic.Password,
		}
	}
	if c.TLS.Enabled {
		cluster.SslOpts = &gocql.SslOptions{
			Config: &tls.Config{
				ServerName: c.TLS.ServerName,
			},
			CertPath:               c.TLS.CertPath,
			KeyPath:                c.TLS.KeyPath,
			CaPath:                 c.TLS.CaPath,
			EnableHostVerification: c.TLS.EnableHostVerification,
		}
	}
	// If tunneling connection to C*, disable cluster autodiscovery features.
	if c.DisableAutoDiscovery {
		cluster.DisableInitialHostLookup = true
		cluster.IgnorePeerAddr = true
	}
	return cluster
}

func (c *Configuration) String() string {
	return fmt.Sprintf("%+v", *c)
}
