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

package model_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"

	"github.com/jaegertracing/jaeger/model"
)

func TestTimeConversion(t *testing.T) {
	s := model.TimeAsEpochMicroseconds(time.Unix(100, 2000))
	assert.Equal(t, uint64(100000002), s)
	assert.True(t, time.Unix(100, 2000).Equal(model.EpochMicrosecondsAsTime(s)))
}

func TestDurationConversion(t *testing.T) {
	d := model.DurationAsMicroseconds(12345 * time.Microsecond)
	assert.Equal(t, 12345*time.Microsecond, model.MicrosecondsAsDuration(d))
	assert.Equal(t, uint64(12345), d)
}

func TestTimeZoneUTC(t *testing.T) {
	ts := model.EpochMicrosecondsAsTime(10000100)
	assert.Equal(t, time.UTC, ts.Location())
}
