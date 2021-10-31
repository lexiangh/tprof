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

package dbmodel

import (
	"testing"

	"github.com/kr/pretty"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/jaegertracing/jaeger/model"
)

var (
	someTraceID       = model.NewTraceID(22222, 44444)
	someSpanID        = model.SpanID(3333)
	someParentSpanID  = model.SpanID(11111)
	someOperationName = "someOperationName"
	someStartTime     = model.EpochMicrosecondsAsTime(55555)
	someDuration      = model.MicrosecondsAsDuration(50000)
	someFlags         = model.Flags(1)
	someLogTimestamp  = model.EpochMicrosecondsAsTime(12345)
	someServiceName   = "someServiceName"

	someStringTagValue = "someTagValue"
	someBoolTagValue   = true
	someLongTagValue   = int64(123)
	someDoubleTagValue = float64(1.4)
	someBinaryTagValue = []byte("someBinaryValue")
	someStringTagKey   = "someStringTag"
	someBoolTagKey     = "someBoolTag"
	someLongTagKey     = "someLongTag"
	someDoubleTagKey   = "someDoubleTag"
	someBinaryTagKey   = "someBinaryTag"
	someTags           = model.KeyValues{
		model.String(someStringTagKey, someStringTagValue),
		model.Bool(someBoolTagKey, someBoolTagValue),
		model.Int64(someLongTagKey, someLongTagValue),
		model.Float64(someDoubleTagKey, someDoubleTagValue),
		model.Binary(someBinaryTagKey, someBinaryTagValue),
	}
	someDBTags = []KeyValue{
		{
			Key:         someStringTagKey,
			ValueType:   stringType,
			ValueString: someStringTagValue,
		},
		{
			Key:       someBoolTagKey,
			ValueType: boolType,
			ValueBool: someBoolTagValue,
		},
		{
			Key:        someLongTagKey,
			ValueType:  int64Type,
			ValueInt64: someLongTagValue,
		},
		{
			Key:          someDoubleTagKey,
			ValueType:    float64Type,
			ValueFloat64: someDoubleTagValue,
		},
		{
			Key:         someBinaryTagKey,
			ValueType:   binaryType,
			ValueBinary: someBinaryTagValue,
		},
	}
	someLogs = []model.Log{
		{
			Timestamp: someLogTimestamp,
			Fields:    someTags,
		},
	}
	someDBLogs = []Log{
		{
			Timestamp: int64(model.TimeAsEpochMicroseconds(someLogTimestamp)),
			Fields:    someDBTags,
		},
	}
	someRefs = []model.SpanRef{
		{
			TraceID: someTraceID,
			SpanID:  someParentSpanID,
			RefType: model.ChildOf,
		},
	}
	someDBProcess = Process{
		ServiceName: someServiceName,
		Tags:        someDBTags,
	}
	badDBTags = []KeyValue{
		{
			Key:       "sneh",
			ValueType: "krustytheklown",
		},
	}
	someDBTraceID = TraceIDFromDomain(someTraceID)
	someDBRefs    = []SpanRef{
		{
			RefType: "child-of",
			SpanID:  int64(someParentSpanID),
			TraceID: someDBTraceID,
		},
	}
	notValidTagTypeErrStr = "invalid ValueType in"
)

func getTestJaegerSpan() *model.Span {
	return &model.Span{
		TraceID:       someTraceID,
		SpanID:        someSpanID,
		OperationName: someOperationName,
		References:    someRefs,
		Flags:         someFlags,
		StartTime:     someStartTime,
		Duration:      someDuration,
		Tags:          someTags,
		Logs:          someLogs,
		Process:       getTestJaegerProcess(),
	}
}

func getTestJaegerProcess() *model.Process {
	return &model.Process{
		ServiceName: someServiceName,
		Tags:        someTags,
	}
}

func getTestSpan() *Span {
	span := &Span{
		TraceID:       someDBTraceID,
		SpanID:        int64(someSpanID),
		OperationName: someOperationName,
		Flags:         int32(someFlags),
		StartTime:     int64(model.TimeAsEpochMicroseconds(someStartTime)),
		Duration:      int64(model.DurationAsMicroseconds(someDuration)),
		Tags:          someDBTags,
		Logs:          someDBLogs,
		Refs:          someDBRefs,
		Process:       someDBProcess,
		ServiceName:   someServiceName,
	}
	// there is no way to validate if the hash code is "correct" or not,
	// other than comparing it with some magic number that keeps changing
	// as the model changes. So let's just make sure the code is being
	// calculated during the conversion.
	spanHash, _ := model.HashCode(getTestJaegerSpan())
	span.SpanHash = int64(spanHash)
	return span
}

func getCustomSpan(dbTags []KeyValue, dbProcess Process, dbLogs []Log, dbRefs []SpanRef) *Span {
	span := getTestSpan()
	span.Tags = dbTags
	span.Logs = dbLogs
	span.Refs = dbRefs
	span.Process = dbProcess
	return span
}

func getTestUniqueTags() []TagInsertion {
	return []TagInsertion{
		{ServiceName: "someServiceName", TagKey: "someBoolTag", TagValue: "true"},
		{ServiceName: "someServiceName", TagKey: "someDoubleTag", TagValue: "1.4"},
		{ServiceName: "someServiceName", TagKey: "someLongTag", TagValue: "123"},
		{ServiceName: "someServiceName", TagKey: "someStringTag", TagValue: "someTagValue"},
	}
}

func TestToSpan(t *testing.T) {
	expectedSpan := getTestSpan()
	actualDBSpan := FromDomain(getTestJaegerSpan())
	if !assert.EqualValues(t, expectedSpan, actualDBSpan) {
		for _, diff := range pretty.Diff(expectedSpan, actualDBSpan) {
			t.Log(diff)
		}
	}
}

func TestFromSpan(t *testing.T) {
	for _, testParentID := range []bool{false, true} {
		testDBSpan := getTestSpan()
		if testParentID {
			testDBSpan.ParentID = testDBSpan.Refs[0].SpanID
			testDBSpan.Refs = nil
		}
		expectedSpan := getTestJaegerSpan()
		actualJSpan, err := ToDomain(testDBSpan)
		assert.NoError(t, err)
		if !assert.EqualValues(t, expectedSpan, actualJSpan) {
			for _, diff := range pretty.Diff(expectedSpan, actualJSpan) {
				t.Log(diff)
			}
		}
	}
}

func TestFailingFromDBSpanBadTags(t *testing.T) {
	faultyDBTags := getCustomSpan(badDBTags, someDBProcess, someDBLogs, someDBRefs)
	failingDBSpanTransform(t, faultyDBTags, notValidTagTypeErrStr)
}

func TestFailingFromDBSpanBadLogs(t *testing.T) {
	faultyDBLogs := getCustomSpan(someDBTags, someDBProcess, []Log{
		{
			Timestamp: 0,
			Fields:    badDBTags,
		},
	}, someDBRefs)
	failingDBSpanTransform(t, faultyDBLogs, notValidTagTypeErrStr)
}

func TestFailingFromDBSpanBadProcess(t *testing.T) {
	faultyDBProcess := getCustomSpan(someDBTags, Process{
		ServiceName: someServiceName,
		Tags:        badDBTags,
	}, someDBLogs, someDBRefs)
	failingDBSpanTransform(t, faultyDBProcess, notValidTagTypeErrStr)
}

func TestFailingFromDBSpanBadRefs(t *testing.T) {
	faultyDBRefs := getCustomSpan(someDBTags, someDBProcess, someDBLogs, []SpanRef{
		{
			RefType: "makeOurOwnCasino",
			TraceID: someDBTraceID,
		},
	})
	failingDBSpanTransform(t, faultyDBRefs, "invalid SpanRefType in")
}

func failingDBSpanTransform(t *testing.T, dbSpan *Span, errMsg string) {
	jSpan, err := ToDomain(dbSpan)
	assert.Nil(t, jSpan)
	require.Error(t, err)
	assert.Contains(t, err.Error(), errMsg)
}

func TestFailingFromDBLogs(t *testing.T) {
	someDBLogs := []Log{
		{
			Timestamp: 0,
			Fields: []KeyValue{
				{
					Key:       "sneh",
					ValueType: "krustytheklown",
				},
			},
		},
	}
	jLogs, err := converter{}.fromDBLogs(someDBLogs)
	assert.Nil(t, jLogs)
	require.Error(t, err)
	assert.Contains(t, err.Error(), notValidTagTypeErrStr)
}

func TestDBTagTypeError(t *testing.T) {
	_, err := converter{}.fromDBTag(&KeyValue{ValueType: "x"})
	assert.Contains(t, err.Error(), notValidTagTypeErrStr)
}

func TestGenerateHashCode(t *testing.T) {
	span1 := getTestJaegerSpan()
	span2 := getTestJaegerSpan()
	hc1, err1 := model.HashCode(span1)
	hc2, err2 := model.HashCode(span2)
	assert.Equal(t, hc1, hc2)
	assert.NoError(t, err1)
	assert.NoError(t, err2)

	span2.Tags = append(span2.Tags, model.String("xyz", "some new tag"))
	hc2, err2 = model.HashCode(span2)
	assert.NotEqual(t, hc1, hc2)
	assert.NoError(t, err2)
}
